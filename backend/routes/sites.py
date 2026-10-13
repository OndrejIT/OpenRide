from django.contrib import admin
from django.contrib.admin.apps import AdminConfig as DjangoAdminConfig


class AdminSite(admin.AdminSite):
    site_header = site_title = "OpenRide"

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        for app in apps:
            if app["app_label"] == "routes":
                # videos first: that is where rides are added
                app["models"].sort(key=lambda m: m["object_name"] != "Video")
        return apps


class AdminConfig(DjangoAdminConfig):
    default_site = "routes.sites.AdminSite"
