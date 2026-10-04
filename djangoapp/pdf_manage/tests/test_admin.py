import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from pdf_manage.models import PdfDocument, PdfVersion

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def pdf_file(filename="資料.pdf"):
    return SimpleUploadedFile(filename, b"%PDF-1.7 dummy body", content_type="application/pdf")


def inline_payload(total=1, initial=0):
    """ドキュメント編集画面のインライン（versions）用 POST データ。"""
    return {
        "versions-TOTAL_FORMS": str(total),
        "versions-INITIAL_FORMS": str(initial),
        "versions-MIN_NUM_FORMS": "0",
        "versions-MAX_NUM_FORMS": "1000",
    }


def test_admin_add_document_with_first_version(admin_client, admin_user):
    response = admin_client.post(
        reverse("admin:pdf_manage_pdfdocument_add"),
        {
            "title": "就業規則",
            "slug": "",
            "description": "",
            "is_published": "on",
            "current_version": "",
            **inline_payload(),
            "versions-0-id": "",
            "versions-0-note": "初版",
            "versions-0-file": pdf_file(),
        },
    )

    assert response.status_code == 302
    document = PdfDocument.objects.get()
    version = document.versions.get()
    assert version.version == 1
    assert version.note == "初版"
    assert version.original_filename == "資料.pdf"
    assert version.uploaded_by == admin_user
    # 1 本目は自動で公開バージョンになる
    assert document.current_version == version


def test_admin_add_second_version_and_switch_current(admin_client):
    document = PdfDocument.objects.create(title="就業規則")
    first = PdfVersion.objects.create(document=document, file=pdf_file())
    url = reverse("admin:pdf_manage_pdfdocument_change", args=[document.pk])

    response = admin_client.post(
        url,
        {
            "title": "就業規則",
            "slug": "",
            "description": "",
            "is_published": "on",
            "current_version": str(first.pk),
            **inline_payload(total=2, initial=1),
            "versions-0-id": str(first.pk),
            "versions-1-id": "",
            "versions-1-note": "第 2 版",
            "versions-1-file": pdf_file("改訂版.pdf"),
        },
    )
    assert response.status_code == 302

    second = document.versions.get(version=2)
    document.refresh_from_db()
    # 新しい版を足しただけでは公開バージョンは動かない
    assert document.current_version == first

    response = admin_client.post(
        url,
        {
            "title": "就業規則",
            "slug": "",
            "description": "",
            "is_published": "on",
            "current_version": str(second.pk),
            **inline_payload(total=2, initial=2),
            "versions-0-id": str(second.pk),
            "versions-1-id": str(first.pk),
        },
    )
    assert response.status_code == 302

    document.refresh_from_db()
    assert document.current_version == second


def test_admin_current_version_choices_are_limited_to_own_versions(admin_client):
    document = PdfDocument.objects.create(title="就業規則")
    own = PdfVersion.objects.create(document=document, file=pdf_file())
    other = PdfDocument.objects.create(title="賃金規程")
    foreign = PdfVersion.objects.create(document=other, file=pdf_file())

    response = admin_client.get(reverse("admin:pdf_manage_pdfdocument_change", args=[document.pk]))
    choices = response.context["adminform"].form.fields["current_version"].queryset

    assert list(choices) == [own]
    assert foreign not in choices
