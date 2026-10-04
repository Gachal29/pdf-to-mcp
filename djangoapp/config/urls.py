from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]

# static() は DEBUG=False のとき空リストを返すので、開発時だけ配信される
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
