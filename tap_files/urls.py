"""tap_files URL configuration — mounted at ``/files/`` by ``tap/urls.py``.

The ``/files`` prefix is reserved against Page slugs through ``TapFilesConfig.reserved_url_prefixes``
(`req-tap-files-download-7`). The route sits behind the login wall and is not exempted from it.

    /files/<identifier>/download     the version the tap_file records, as an attachment
"""

from django.urls import path

from tap_files import views

urlpatterns = [
    path("<str:identifier>/download", views.download, name="tap_files_download"),
]
