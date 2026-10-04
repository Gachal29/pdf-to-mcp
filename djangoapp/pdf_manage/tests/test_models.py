import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from pdf_manage.models import PdfDocument, PdfVersion

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    """アップロードされたファイルをテストごとの一時ディレクトリに閉じ込める。"""
    settings.MEDIA_ROOT = tmp_path


def upload(document, content=b"%PDF-1.7 dummy body", filename="資料.pdf"):
    return PdfVersion.objects.create(
        document=document,
        file=SimpleUploadedFile(filename, content, content_type="application/pdf"),
    )


@pytest.fixture
def document():
    return PdfDocument.objects.create(title="就業規則")


def test_version_numbers_start_at_1_and_increment(document):
    assert [upload(document).version for _ in range(3)] == [1, 2, 3]


def test_version_numbers_are_counted_per_document(document):
    other = PdfDocument.objects.create(title="賃金規程")
    upload(document)
    upload(document)

    assert upload(other).version == 1


def test_upload_path_is_scoped_to_document_and_version(document):
    version = upload(document)

    assert version.file.name.startswith(f"pdfs/{document.id}/v1/")
    assert version.file.name.endswith(".pdf")
    # 保存名は UUID に置き換わり、元の名前はファイルパスに出さない
    assert "資料" not in version.file.name


def test_file_metadata_is_recorded_on_upload(document):
    content = b"%PDF-1.7 content for checksum"
    version = upload(document, content=content)

    assert version.original_filename == "資料.pdf"
    assert version.file_size == len(content)
    assert version.checksum == hashlib.sha256(content).hexdigest()


def test_stored_file_keeps_the_uploaded_bytes(document):
    content = b"%PDF-1.7 content for checksum"
    version = upload(document, content=content)

    with version.file.open("rb") as stored:
        assert stored.read() == content


def test_first_version_becomes_current_and_later_ones_do_not(document):
    first = upload(document)
    document.refresh_from_db()
    assert document.current_version == first

    second = upload(document)
    document.refresh_from_db()
    assert document.current_version == first
    assert document.latest_version == second


def test_current_version_can_be_rolled_back(document):
    first = upload(document)
    second = upload(document)

    document.current_version = second
    document.save()
    document.current_version = first
    document.save()

    document.refresh_from_db()
    assert document.current_version == first
    assert first.is_current is True


def test_deleting_the_current_version_leaves_the_document(document):
    version = upload(document)
    version.delete()

    document.refresh_from_db()
    assert document.current_version is None
    assert PdfDocument.objects.filter(pk=document.pk).exists()


def test_blank_slug_is_stored_as_null_so_it_can_repeat():
    PdfDocument.objects.create(title="規程 A", slug="")
    PdfDocument.objects.create(title="規程 B")

    assert PdfDocument.objects.filter(slug__isnull=True).count() == 2


def test_current_version_must_belong_to_the_document(document):
    other = PdfDocument.objects.create(title="賃金規程")
    foreign_version = upload(other)

    document.current_version = foreign_version
    with pytest.raises(ValidationError) as excinfo:
        document.full_clean()

    assert "current_version" in excinfo.value.message_dict


def test_non_pdf_upload_is_rejected(document):
    version = PdfVersion(
        document=document,
        file=SimpleUploadedFile("note.txt", b"not a pdf", content_type="text/plain"),
    )

    with pytest.raises(ValidationError) as excinfo:
        version.full_clean(exclude=["version", "original_filename", "file_size", "checksum"])

    assert "file" in excinfo.value.message_dict
