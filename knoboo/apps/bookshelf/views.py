from django.conf import settings
from django.shortcuts import render_to_response
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext
from django.utils import simplejson as json
from django.contrib.auth.decorators import login_required

from apps.bookshelf import models as bookshelf_models
from apps.notebook import models as notebook_models

@login_required
def bookshelf(request, template_name='bookshelf/bookshelf.html'):
    """Render the Bookshelf interface.
    """
    return render_to_response(template_name, 
        {'notebook_types':settings.NOTEBOOK_TYPES, 'path':request.path}, context_instance=RequestContext(request))

@login_required
def load_bookshelf_data(request):
    """Retrieve a user's Notebooks for the Bookshelf.

    Handles the current location (all, trash, archive, folder id) as well
    and the order (asc or desc) and field that it is to be sorted on.
    """ 
    location, order, sort = [request.GET.get(v, '') for v in ['location', 'order', 'sort']]
    if order == "lastmodified":
        order = "created_time" #XXX
    if sort == "desc":
        order = "-"+order
    q = notebook_models.Notebook.objects.filter(owner=request.user, location=location).order_by(order)
    data = [[e.guid, e.title, e.system, e.last_modified_time(request.user, e), e.location] for e in q]
    jsobj = json.dumps(data)
    return HttpResponse(jsobj, mimetype='application/json')


@login_required
def folders(request):
    """Handle creating, retrieving, updating, deleting of folders.
    """
    if request.method == "GET":
        q = bookshelf_models.Folder.objects.filter(owner=request.user)
        data = [[e.guid, e.title] for e in q]
    if request.method == "POST":
        if "create" in request.POST:
            newfolder = bookshelf_models.Folder(owner=request.user, title="New Folder")
            newfolder.save()
            data = [[newfolder.guid, "New Folder"]]
        if "update" in request.POST:
            guid = request.POST.get("id", "")
            folder = bookshelf_models.Folder.objects.get(guid=guid)
            folder.title = request.POST.get("newname", "")
            folder.save()
            data = [[folder.guid, folder.title]]
        if "delete" in request.POST:
            folderid = request.POST.get("folderid", "")
            nbids =  request.POST.getlist("nbids")
            folder = bookshelf_models.Folder.objects.get(owner=request.user, guid=folderid)
            folder.delete()
            for nbid in nbids:
                nb = notebook_models.Notebook.objects.get(owner=request.user, guid=nbid)
                nb.delete()
            data = {"response":"ok"}
    jsobj = json.dumps(data)
    return HttpResponse(jsobj, mimetype='application/json')


@login_required
def change_notebook_location(request):
    """Move one or more notebooks to a different location in the Bookshelf.
    """
    dest = request.POST.get("dest" '')
    ids = request.POST.getlist("nbid")
    for nbid in ids:
        nb = notebook_models.Notebook.objects.get(owner=request.user, guid=nbid)
        nb.location = dest
        nb.save()
    jsobj = json.dumps({"response":"ok"})
    return HttpResponse(jsobj, mimetype='application/json')


@login_required
def new_notebook(request):
    """Create a new Notebook.
    """
    system = request.GET.get("system", "")
    nb = notebook_models.Notebook(owner=request.user, system=system, title="Untitled", location="root")
    nb.save()
    redirect = "/notebook/%s" % nb.guid
    return HttpResponseRedirect(redirect)


@login_required
def empty_trash(request):
    """Permanently delete all Notebooks in the Trash section of the Bookshelf.
    """ 
    nbids = request.POST.getlist("nbids")
    for nbid in nbids:
        nb = notebook_models.Notebook.objects.get(owner=request.user, guid=nbid)
        nb.delete()
    jsobj = json.dumps({"response":"ok"})
    return HttpResponse(jsobj, mimetype='application/json')

