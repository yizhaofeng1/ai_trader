from django import forms
from .models import AnalysisRecord

class ImageUploadForm(forms.ModelForm):
    class Meta:
        model = AnalysisRecord
        fields = ['chart_image']
        widgets = {
            'chart_image': forms.FileInput(attrs={'class': 'form-control'})
        }