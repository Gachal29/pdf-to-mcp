import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction


def pdf_upload_path(instance, filename):
    """保存先を pdfs/<ドキュメント UUID>/v<バージョン>/<UUID>.pdf にする。

    ファイル名を UUID に置き換えるのは、日本語ファイル名の文字化けと同名衝突を
    避けるため。表示やダウンロードに使う元の名前は original_filename に残す。
    """
    suffix = Path(filename).suffix.lower() or ".pdf"
    return f"pdfs/{instance.document_id}/v{instance.version}/{uuid.uuid4()}{suffix}"


class PdfDocument(models.Model):
    """MCP エンドポイント 1 つに対応する論理ドキュメント。

    PDF の実体は持たず、PdfVersion を束ねて「どの版を配信するか」を決める。
    """

    id = models.UUIDField("ID", primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField("タイトル", max_length=200)
    slug = models.SlugField(
        "スラッグ",
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="URL に使う任意の識別子。未入力の場合は UUID だけで参照する。",
    )
    description = models.TextField("説明", blank=True)
    current_version = models.ForeignKey(
        "PdfVersion",
        verbose_name="公開バージョン",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="MCP が配信するバージョン。切り替えると過去の版に戻せる。",
    )
    is_published = models.BooleanField("公開中", default=False)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "PDF ドキュメント"
        verbose_name_plural = "PDF ドキュメント"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.current_version_id and self.current_version.document_id != self.id:
            message = "他のドキュメントのバージョンは公開バージョンに指定できません。"
            raise ValidationError({"current_version": message})

    def save(self, *args, **kwargs):
        # slug は unique なので、空文字のまま複数保存すると衝突する。未入力は NULL に寄せる
        if not self.slug:
            self.slug = None
        super().save(*args, **kwargs)

    @property
    def latest_version(self):
        """最新のバージョン。1 本も無ければ None。"""
        return self.versions.first()


class PdfVersion(models.Model):
    """アップロードされた PDF ファイルそのもの。作成後は差し替えず、新しい版を積む。"""

    document = models.ForeignKey(
        PdfDocument,
        verbose_name="ドキュメント",
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField("バージョン", editable=False)
    file = models.FileField(
        "PDF ファイル",
        upload_to=pdf_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
    )
    original_filename = models.CharField("元のファイル名", max_length=255, editable=False)
    file_size = models.PositiveBigIntegerField("ファイルサイズ", editable=False)
    checksum = models.CharField("SHA-256", max_length=64, editable=False)
    note = models.TextField("変更メモ", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="アップロード者",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    uploaded_at = models.DateTimeField("アップロード日時", auto_now_add=True)

    class Meta:
        verbose_name = "PDF バージョン"
        verbose_name_plural = "PDF バージョン"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version"], name="pdf_manage_unique_version_per_document"
            )
        ]

    def __str__(self):
        return f"{self.document.title} v{self.version}"

    @property
    def is_current(self):
        return self.document.current_version_id == self.pk

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)

        with transaction.atomic():
            self.version = self._next_version()
            self._fill_file_metadata()
            super().save(*args, **kwargs)
            self._adopt_as_current_if_first()

    def _next_version(self):
        # ドキュメント行をロックしてから最大値を読む。同時アップロードで同じ番号が
        # 振られるのを防ぐ（unique 制約の手前で直列化する）
        list(PdfDocument.objects.select_for_update().filter(pk=self.document_id).values_list("pk"))
        latest = PdfVersion.objects.filter(document_id=self.document_id).aggregate(
            models.Max("version")
        )["version__max"]
        return (latest or 0) + 1

    def _fill_file_metadata(self):
        # 保存前の FieldFile.name はアップロードされた元のファイル名を指す
        self.original_filename = Path(self.file.name).name
        digest = hashlib.sha256()
        size = 0
        for chunk in self.file.chunks():
            digest.update(chunk)
            size += len(chunk)
        self.checksum = digest.hexdigest()
        self.file_size = size

    def _adopt_as_current_if_first(self):
        # 1 本目は選びようがないので自動で公開バージョンにする。
        # 2 本目以降は管理画面で明示的に切り替えるまで公開版を変えない
        updated = PdfDocument.objects.filter(
            pk=self.document_id, current_version__isnull=True
        ).update(current_version=self)
        if updated:
            self.document.current_version = self
