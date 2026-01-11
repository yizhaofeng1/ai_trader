"""
URL configuration for ai_trader project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from market_scanner import views

urlpatterns = [
                  path('admin/', admin.site.urls),
                  path('', views.dashboard, name='dashboard'),
                  path('delete/<int:pk>/', views.delete_record, name='delete_record'),

                  # API Endpoints
                  path('api/login/', views.api_login, name='api_login'),
                  path('api/register/', views.api_register, name='api_register'),
                  path('api/reset-password/', views.api_reset_password, name='api_reset_password'),
                  path('api/logout/', views.api_logout, name='api_logout'),
                  path('api/fetch-models/', views.fetch_external_models, name='fetch_models'),
                  path('api/save-settings/', views.save_settings, name='save_settings'),
                  path('api/save-strategy/', views.save_strategy_config, name='save_strategy'),


path('trade/ticket/<int:record_id>/', views.trade_ticket_view, name='trade_ticket'),
path('api/trade/execute/', views.execute_paper_order, name='execute_order'),

              ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
