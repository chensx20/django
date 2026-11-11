from django.contrib.admindocs.middleware import XViewMiddleware
from django.http import HttpResponse
from django.utils.decorators import decorator_from_middleware
from django.views.generic import View

xview_dec = decorator_from_middleware(XViewMiddleware)


def xview(request):
    """Display a documented view.

    Display an individual :model:`admin_docs.Person`.

    ``person``
        An instance of :model:`admin_docs.Person`.

    Context: the person
    Templates: :template:`person.html`
    """
    return HttpResponse()


class XViewClass(View):
    def get(self, request):
        return HttpResponse()


class XViewCallableObject(View):
    def __call__(self, request):
        return HttpResponse()
