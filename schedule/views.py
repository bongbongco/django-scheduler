from urllib import quote
from django.shortcuts import render_to_response, get_object_or_404
from django.views.generic.create_update import delete_object
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.template import RequestContext
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.generic.create_update import delete_object
import datetime

from schedule.conf.settings import GET_EVENTS_FUNC, CHECK_PERMISSION_FUNC, OCCURRENCE_CANCEL_REDIRECT
from schedule.forms import EventForm, OccurrenceForm
from schedule.forms import OccurrenceBackendForm
from schedule.models import *
from schedule.periods import weekday_names
from schedule.utils import check_event_permissions, coerce_date_dict
from schedule.utils import encode_occurrence, decode_occurrence

def calendar(request, calendar_slug, template='schedule/calendar.html'):
    """
    This view returns a calendar.  This view should be used if you are
    interested in the meta data of a calendar, not if you want to display a
    calendar.  It is suggested that you use calendar_by_periods if you would
    like to display a calendar.

    Context Variables:

    ``calendar``
        The Calendar object designated by the ``calendar_slug``.
    """
    calendar = get_object_or_404(Calendar, slug=calendar_slug)
    return render_to_response(template, {
        "calendar": calendar,
    }, context_instance=RequestContext(request))

def calendar_by_periods(request, calendar_slug, periods=None,
    template_name="schedule/calendar_by_period.html"):
    """
    This view is for getting a calendar, but also getting periods with that
    calendar.  Which periods you get, is designated with the list periods. You
    can designate which date you the periods to be initialized to by passing
    a date in request.GET. See the template tag ``query_string_for_date``

    Context Variables

    ``date``
        This was the date that was generated from the query string.

    ``periods``
        this is a dictionary that returns the periods from the list you passed
        in.  If you passed in Month and Day, then your dictionary would look
        like this

        {
            'month': <schedule.periods.Month object>
            'day':   <schedule.periods.Day object>
        }

        So in the template to access the Day period in the context you simply
        use ``periods.day``.

    ``calendar``
        This is the Calendar that is designated by the ``calendar_slug``.

    ``weekday_names``
        This is for convenience. It returns the local names of weekedays for
        internationalization.

    """
    calendar = get_object_or_404(Calendar, slug=calendar_slug)
    date = coerce_date_dict(request.GET)
    if date:
        try:
            date = datetime.datetime(**date)
        except ValueError:
            raise Http404
    else:
        date = datetime.datetime.now()
    event_list = GET_EVENTS_FUNC(request, calendar)
    period_objects = dict([(period.__name__.lower(), period(event_list, date)) for period in periods])
    return render_to_response(template_name,{
            'date': date,
            'periods': period_objects,
            'calendar': calendar,
            'weekday_names': weekday_names,
            'here':quote(request.get_full_path()),
        },context_instance=RequestContext(request),)

def event(request, event_id, template_name="schedule/event.html"):
    """
    This view is for showing an event. It is important to remember that an
    event is not an occurrence.  Events define a set of reccurring occurrences.
    If you would like to display an occurrence (a single instance of a
    recurring event) use occurrence.

    Context Variables:

    event
        This is the event designated by the event_id

    back_url
        this is the url that referred to this view.
    """
    event = get_object_or_404(Event, id=event_id)
    back_url = request.META.get('HTTP_REFERER', None)
    try:
        cal = event.calendar_set.get()
    except:
        cal = None
    return render_to_response(template_name, {
        "event": event,
        "back_url" : back_url,
    }, context_instance=RequestContext(request))

def occurrence(request, event_id,
    template_name="schedule/occurrence.html", *args, **kwargs):
    """
    This view is used to display an occurrence.

    Context Variables:

    ``event``
        the event that produces the occurrence

    ``occurrence``
        the occurrence to be displayed

    ``back_url``
        the url from which this request was refered
    """
    event, occurrence = get_occurrence(event_id, *args, **kwargs)
    back_url = request.META.get('HTTP_REFERER', None)
    return render_to_response(template_name, {
        'event': event,
        'occurrence': occurrence,
        'back_url': back_url,
    }, context_instance=RequestContext(request))


@check_event_permissions
def edit_occurrence(request, event_id,
    template_name="schedule/edit_occurrence.html", *args, **kwargs):
    event, occurrence = get_occurrence(event_id, *args, **kwargs)
    next = kwargs.get('next', None)
    form = OccurrenceForm(data=request.POST or None, instance=occurrence)
    if form.is_valid():
        occurrence = form.save(commit=False)
        occurrence.event = event
        occurrence.save()
        next = next or get_next_url(request, occurrence.get_absolute_url())
        return HttpResponseRedirect(next)
    next = next or get_next_url(request, occurrence.get_absolute_url())
    return render_to_response(template_name, {
        'form': form,
        'occurrence': occurrence,
        'next':next,
    }, context_instance=RequestContext(request))


@check_event_permissions
def cancel_occurrence(request, event_id,
    template_name='schedule/cancel_occurrence.html', *args, **kwargs):
    """
    This view is used to cancel an occurrence. If it is called with a POST it
    will cancel the view. If it is called with a GET it will ask for
    conformation to cancel.
    """
    event, occurrence = get_occurrence(event_id, *args, **kwargs)
    next = kwargs.get('next',None) or get_next_url(request, event.get_absolute_url())
    if request.method != "POST":
        return render_to_response(template_name, {
            "occurrence": occurrence,
            "next":next,
        }, context_instance=RequestContext(request))
    occurrence.cancel()
    return HttpResponseRedirect(next)


def get_occurrence(event_id, occurrence_id=None, year=None, month=None,
    day=None, hour=None, minute=None, second=None):
    """
    Because occurrences don't have to be persisted, there must be two ways to
    retrieve them. both need an event, but if its persisted the occurrence can
    be retrieved with an id. If it is not persisted it takes a date to
    retrieve it.  This function returns an event and occurrence regardless of
    which method is used.
    """
    if(occurrence_id):
        occurrence = get_object_or_404(Occurrence, id=occurrence_id)
        event = occurrence.event
    elif not [x for x in (year, month, day, hour, minute, second) if x is None]:
        event = get_object_or_404(Event, id=event_id)
        occurrence = event.get_occurrence(
            datetime.datetime(int(year), int(month), int(day), int(hour),
                int(minute), int(second)))
        if occurrence is None:
            raise Http404
    else:
        raise Http404
    return event, occurrence


@check_event_permissions
def create_or_edit_event(request, calendar_slug, event_id=None, next=None,
    template_name='schedule/create_event.html', form_class = EventForm):
    """
    This function, if it receives a GET request or if given an invalid form in a
    POST request it will generate the following response

    Template:
        schedule/create_event.html

    Context Variables:

    form:
        an instance of EventForm

    calendar:
        a Calendar with id=calendar_id

    if this function gets a GET request with ``year``, ``month``, ``day``,
    ``hour``, ``minute``, and ``second`` it will auto fill the form, with
    the date specifed in the GET being the start and 30 minutes from that
    being the end.

    If this form receives an event_id it will edit the event with that id, if it
    recieves a calendar_id and it is creating a new event it will add that event
    to the calendar with the id calendar_id

    If it is given a valid form in a POST request it will redirect with one of
    three options, in this order

    # Try to find a 'next' GET variable
    # If the key word argument redirect is set
    # Lastly redirect to the event detail of the recently create event
    """
    date = coerce_date_dict(request.GET)
    initial_data = None
    if date:
        try:
            start = datetime.datetime(**date)
            initial_data = {
                "start": start,
                "end": start + datetime.timedelta(minutes=30)
            }
        except TypeError:
            raise Http404
        except ValueError:
            raise Http404

    instance = None
    if event_id is not None:
        instance = get_object_or_404(Event, id=event_id)

    calendar = get_object_or_404(Calendar, slug=calendar_slug)

    form = form_class(data=request.POST or None, instance=instance,
        hour24=True, initial=initial_data)

    if form.is_valid():
        event = form.save(commit=False)
        if instance is None:
            event.creator = request.user
            event.calendar = calendar
        event.save()
        next = next or reverse('event', args=[event.id])
        next = get_next_url(request, next)
        return HttpResponseRedirect(next)

    next = get_next_url(request, next)
    return render_to_response(template_name, {
        "form": form,
        "calendar": calendar,
        "next":next
    }, context_instance=RequestContext(request))


@check_event_permissions
def delete_event(request, event_id, next=None, login_required=True):
    """
    After the event is deleted there are three options for redirect, tried in
    this order:

    # Try to find a 'next' GET variable
    # If the key word argument redirect is set
    # Lastly redirect to the event detail of the recently create event
    """
    event = get_object_or_404(Event, id=event_id)
    next = next or reverse('day_calendar', args=[event.calendar.slug])
    next = get_next_url(request, next)
    return delete_object(request,
                         model = Event,
                         object_id = event_id,
                         post_delete_redirect = next,
                         template_name = "schedule/delete_event.html",
                         extra_context = dict(next=next),
                         login_required = login_required
                        )

def check_next_url(next):
    """
    Checks to make sure the next url is not redirecting to another page.
    Basically it is a minimal security check.
    """
    if not next or '://' in next:
        return None
    return next

def get_next_url(request, default):
    next = default
    if OCCURRENCE_CANCEL_REDIRECT:
        next = OCCURRENCE_CANCEL_REDIRECT
    if 'next' in request.REQUEST and check_next_url(request.REQUEST['next']) is not None:
        next = request.REQUEST['next']
    return next


from schedule.periods import Week

def weekcalendarjs(request, calendar_slug):
    config_params = {} # will draw from settings
    config_params['calendar_slug'] = calendar_slug
    start_date_dict = coerce_date_dict(request.GET)
    start_date = datetime.date(start_date_dict['year'], start_date_dict['month'], start_date_dict['day'])
    target_week = Week([], start_date)
    if target_week != Week([]): # is it current period?
        config_params['start_date'] = start_date
    return render_to_response('schedule/weekcalendar.js', config_params)

def schedulelibjs(request):
    config_params = {} # will draw from settings
    return render_to_response('schedule/schedule_lib.js', config_params)


from django.template import Context, loader

def calendar_by_periods_json(request, calendar_slug, periods, template_name='schedule/occurrences_json.html'):
    # XXX is this function name good?
    user = request.user
    calendar = get_object_or_404(Calendar, slug=calendar_slug)
    date = coerce_date_dict(request.GET)
    if date:
        try:
            date = datetime.datetime(**date)
        except ValueError:
            raise Http404
    else:
        date = datetime.datetime.now()
    event_list = GET_EVENTS_FUNC(request, calendar)
    period_object = periods[0](event_list, date)
    occ_list = []
    for i, occ in enumerate(period_object.occurrences):
        res = period_object.classify_occurrence(occ)
        if res:
            original_id = occ.id
            occ.id = encode_occurrence(occ)
            occ.start = occ.start.ctime()
            occ.end = occ.end.ctime()
            occ.read_only = not CHECK_PERMISSION_FUNC(occ, user)
            occ.recurring = bool(occ.event.rule)
            occ.persisted = bool(original_id)
            # these attributes are very important from UI point of view
            # if occ is recurreing and not persisted then a user can edit either event or occurrence
            # once an occ has been edited it is persisted so he can edit only occurrence
            # if occ represents non-recurring event then he always edits the event
            occ_list.append(occ)
    rnd = loader.get_template(template_name)
    resp = rnd.render(Context({'occurrences':period_object.occurrences}))
    return HttpResponse(resp)


# TODO permissions check
def edit_occurrence_by_code(request):
    try:
        id = request.REQUEST.get('id')
        kwargs = decode_occurrence(id)
        event_id = kwargs.pop('event_id')
        event, occurrence = get_occurrence(event_id, **kwargs)
        if request.REQUEST.get('action') == 'cancel':
            occurrence.cancel()
            return HttpResponse('OK')
        form = OccurrenceBackendForm(data=request.POST or None, instance=occurrence)
        if form.is_valid():
            occurrence = form.save(commit=False)
            occurrence.event = event
            occurrence.save()
            return HttpResponse('OK')
        return HttpResponse(str(form.errors))
    except Exception, e:
        return HttpResponse(str(e))


