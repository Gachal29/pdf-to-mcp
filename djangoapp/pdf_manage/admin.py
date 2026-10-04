from django.contrib import admin

from .models import PdfDocument, PdfVersion

COMPUTED_FIELDS = (
    "version",
    "original_filename",
    "file_size",
    "checksum",
    "uploaded_by",
    "uploaded_at",
)


class PdfVersionInline(admin.TabularInline):
    """ドキュメント編集画面から新しい版を足すためのインライン。"""

    model = PdfVersion
    fk_name = "document"
    extra = 1
    fields = (*COMPUTED_FIELDS, "file", "note")
    readonly_fields = COMPUTED_FIELDS
    ordering = ("-version",)

    def has_change_permission(self, request, obj=None):
        # 既存の版は差し替えない。内容を変えたいときは新しい版を足す
        return False


@admin.register(PdfDocument)
class PdfDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "current_version", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug", "description")
    fields = (
        "id",
        "title",
        "slug",
        "description",
        "is_published",
        "current_version",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [PdfVersionInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "current_version":
            # 公開バージョンには、このドキュメント自身の版だけを出す
            object_id = (
                request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            )
            kwargs["queryset"] = (
                PdfVersion.objects.filter(document_id=object_id)
                if object_id
                else PdfVersion.objects.none()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, PdfVersion) and instance.uploaded_by_id is None:
                instance.uploaded_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(PdfVersion)
class PdfVersionAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "version",
        "original_filename",
        "file_size",
        "is_current",
        "uploaded_at",
    )
    list_filter = ("document",)
    search_fields = ("original_filename", "document__title")
    fields = (
        "document",
        "version",
        "file",
        "original_filename",
        "file_size",
        "checksum",
        "note",
        "uploaded_by",
        "uploaded_at",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return COMPUTED_FIELDS
        # 保存済みの版はファイルもドキュメントも動かさない。直せるのはメモだけ
        return (*COMPUTED_FIELDS, "document", "file")

    @admin.display(boolean=True, description="公開中")
    def is_current(self, obj):
        return obj.is_current

    def save_model(self, request, obj, form, change):
        if obj.uploaded_by_id is None:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
