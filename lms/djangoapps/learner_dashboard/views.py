"""Learner dashboard views"""
from urlparse import urljoin

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_GET
from opaque_keys.edx.keys import CourseKey

from edxmako.shortcuts import render_to_response
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.credentials.utils import get_programs_credentials
from openedx.core.djangoapps.programs.models import ProgramsApiConfig
from openedx.core.djangoapps.programs.utils import ProgramProgressMeter, get_programs, get_display_category
from student.models import CourseEnrollment
from student.views import get_course_enrollments


@login_required
@require_GET
def view_programs(request):
    """View programs in which the user is engaged."""
    show_program_listing = ProgramsApiConfig.current().show_program_listing
    if not show_program_listing:
        raise Http404

    enrollments = list(get_course_enrollments(request.user, None, []))
    meter = ProgramProgressMeter(request.user, enrollments)
    programs = meter.engaged_programs

    # TODO: Pull 'xseries' string from configuration model.
    marketing_root = urljoin(settings.MKTG_URLS.get('ROOT'), 'xseries').strip('/')
    for program in programs:
        program['display_category'] = get_display_category(program)
        program['marketing_url'] = '{root}/{slug}'.format(
            root=marketing_root,
            slug=program['marketing_slug']
        )

    context = {
        'programs': programs,
        'progress': meter.progress,
        'xseries_url': marketing_root if ProgramsApiConfig.current().show_xseries_ad else None,
        'nav_hidden': True,
        'show_program_listing': show_program_listing,
        'credentials': get_programs_credentials(request.user, category='xseries'),
        'disable_courseware_js': True,
        'uses_pattern_library': True
    }

    return render_to_response('learner_dashboard/programs.html', context)


@login_required
@require_GET
def program_details(request, program_id):
    """View details about a specific program."""
    show_program_details = ProgramsApiConfig.current().show_program_details
    if not show_program_details:
        raise Http404

    program_data = get_programs(request.user, program_id=program_id)

    for course_code in program_data.get('course_codes', []):
        for run_mode in course_code['run_modes']:
            course_key = CourseKey.from_string(run_mode['course_key'])
            course_overview = CourseOverview.get_from_id(course_key)

            run_mode['course_url'] = reverse('course_root', args=[course_key])
            run_mode['course_image_url'] = course_overview.course_image_url

            # TODO: Use locale’s appropriate date representation? (i.e., %x)
            human_friendly_format = '%B %-d, %Y'
            run_mode['start_date'] = course_overview.start.strftime(human_friendly_format)
            run_mode['end_date'] = course_overview.end.strftime(human_friendly_format)

            run_mode['is_enrolled'] = CourseEnrollment.is_enrolled(request.user, course_key)

            # TODO: Confirm that all times are UTC.
            is_enrollment_open = course_overview.enrollment_start <= timezone.now() < course_overview.enrollment_end
            run_mode['is_enrollment_open'] = is_enrollment_open

            # TODO: Currently unavailable on LMS.
            run_mode['marketing_url'] = ''

    context = {
        'program_data': program_data,
        'nav_hidden': True,
        'disable_courseware_js': True,
        'uses_pattern_library': True
    }

    return render_to_response('learner_dashboard/program_details.html', context)
