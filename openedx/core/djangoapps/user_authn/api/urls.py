"""
Authn API urls
"""

from django.conf.urls import url

from openedx.core.djangoapps.user_authn.api.views import TPAContextView, MFEAppContextView

urlpatterns = [
    url(r'^third_party_auth_context$', TPAContextView.as_view(), name='third_party_auth_context'),
    url(r'^mfe_app_auth_context$', MFEAppContextView.as_view(), name='mfe_app_auth_context'),
]
