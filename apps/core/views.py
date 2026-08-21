from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Placeholder do FEAT-001. O grid de INEPs (RF-05) entra no FEAT-007."""
    return render(request, "core/home.html")
