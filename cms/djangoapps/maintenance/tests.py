"""
Tests for the maintenance app views.
"""
import ddt
import itertools

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from student.roles import GlobalStaff
from student.tests.factories import AdminFactory, UserFactory

from contentstore.management.commands.utils import get_course_versions

from .views import COURSE_KEY_ERROR_MESSAGES, get_maintenace_urls



class TestMaintenanceIndex(ModuleStoreTestCase):
    """
    Tests for maintenance index view.
    """

    def setUp(self):
        """Make the user global staff. """
        super(TestMaintenanceIndex, self).setUp()
        self.user = AdminFactory()
        login_success = self.client.login(username=self.user.username, password='test')
        self.assertTrue(login_success)
        self.view_url = reverse('maintenance:maintenance')

    def test_maintenance_index(self):
        response = self.client.get(self.view_url)
        self.assertContains(response, "Maintenance", status_code=200)

        # Check that all the expected links appear on the index page.
        for url in get_maintenace_urls():
            self.assertContains(response, url, status_code=200)


class MaintenanceViewTestCase(ModuleStoreTestCase):
    """
    Base class for maintenance view tests.
    """

    def setUp(self):
        """Create a user and log in. """
        super(MaintenanceViewTestCase, self).setUp()
        self.user = AdminFactory()
        login_success = self.client.login(username=self.user.username, password='test')
        self.assertTrue(login_success)
        self.course = CourseFactory.create(default_store=ModuleStoreEnum.Type.split)

    def verify_error_message(self, data, error_msg):
        """Verify the response contains error message."""
        response = self.client.post(self.view_url, data=data)
        self.assertContains(response, error_msg, status_code=200)

    def validate_success_from_response(self, response, success_message):
        """Validate response contains success."""
        self.assertNotContains(response, '<div class="error">', status_code=200)
        self.assertContains(response, success_message, status_code=200)

    @ddt.data(
        ('', COURSE_KEY_ERROR_MESSAGES['empty_course_key']),
        ('edx', COURSE_KEY_ERROR_MESSAGES['invalid_course_key']),
        ('course-v1:e+d+X', COURSE_KEY_ERROR_MESSAGES['course_key_not_found'])
    )
    def test_invalid_course_key_messages(self, course_key, error_message):
        """
        Test all error messages for invalid course keys.
        """
        # validate course key contains error message
        self.verify_error_message(
            {
                'course-id': course_key
            },
            _(error_message)
        )

    def tearDown(self):
        """
        Reverse the setup
        """
        self.client.logout()
        ModuleStoreTestCase.tearDown(self)


@ddt.ddt
class MaintenanceViewAccessTests(MaintenanceViewTestCase):
    """
    Tests for access control of maintenance views.
    """
    @ddt.data(get_maintenace_urls())
    @ddt.unpack
    def test_require_login(self, url_name):
        url = reverse(url_name)

        # Log out then try to retrieve the page
        self.client.logout()
        response = self.client.get(url)

        # Expect a redirect to the login page
        redirect_url = "{login_url}?next={original_url}".format(
            login_url=reverse("login"),
            original_url=url,
        )

        self.assertRedirects(response, redirect_url)

    # @ddt.data(*(
    #     (url_name, role, has_access)
    #     for (url_name, (role, has_access))
    #     in itertools.product((
    #         "maintenance:maintenance",
    #         "maintenance:force_publish_course"
    #         "maintenance:maintenance",
    #         "maintenance:force_publish_course"
    #         "maintenance:maintenance",
    #         "maintenance:force_publish_course"
    #         "maintenance:maintenance",
    #         "maintenance:force_publish_course"
    #     ), (
    #         (GlobalStaff, True),
    #         (None, False)
    #     ))
    # ))
    @ddt.data(get_maintenace_urls())
    @ddt.unpack
    def test_global_staff_access(self, url_name):
        """
        Test that all maintenance app views are accessible to global staff user.
        """
        url = reverse(url_name)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    @ddt.data(get_maintenace_urls())
    @ddt.unpack
    def test_non_global_staff_access(self, url_name):
        """
        Test that all maintenance app views are not accessible to non-global-staff user.
        """
        user = UserFactory(username='test', email="test@example.com", password="test")
        login_success = self.client.login(username=user.username, password='test')
        self.assertTrue(login_success)

        url = reverse(url_name)
        response = self.client.get(url)

        self.assertContains(response, _('Must be edX staff to perform this action.'), status_code=403)


@ddt.ddt
class TestForcePublish(MaintenanceViewTestCase):
    """
    Tests for the force publish view.
    """

    def setUp(self):
        super(TestForcePublish, self).setUp()
        self.view_url = reverse('maintenance:force_publish_course')
        # Add some changes to course
        chapter = ItemFactory.create(category='chapter', parent_location=self.course.location)
        self.store.create_child(
            self.user.id,  # pylint: disable=no-member
            chapter.location,
            'html',
            block_id='html_component'
        )
        # verify that course has changes.
        self.assertTrue(self.store.has_changes(self.store.get_item(self.course.location)))

    def test_non_split_course(self):
        """
        Test that we get a error message on non-split courses.
        """
        # validate non split error message
        course = CourseFactory.create(default_store=ModuleStoreEnum.Type.mongo)
        self.verify_error_message(
            {
                'course-id': unicode(course.id)
            },
            _('Force publish course does not support old mongo style courses.')
        )

    def test_already_published(self):
        """
        Test that when a course is forcefully publish, we get a 'course is already published' message.
        """
        # Validate course already published
        response = self.force_publish_course()
        self.validate_success_from_response(response, _('Now published and draft branch have same version'))

        # now course is forcefully published, we should get already published course.
        self.verify_error_message(
            {
                'course-id': unicode(self.course.id),
                'dry-run': False
            },
            _('Course is already in published state.')
        )

    def verify_versions_are_different(self):
        """
        Verify draft and published versions point to different locations.
        """
        # get draft and publish branch versions
        versions = get_course_versions(unicode(self.course.id))

        # verify that draft and publish point to different versions
        self.assertNotEqual(versions['draft-branch'], versions['published-branch'])

    def force_publish_course(self, is_dry_run=''):
        """
        Force publish the course.
        """
        # Verify versions point to different locations initially
        self.verify_versions_are_different()

        # force publish course
        data = {
            'course-id': unicode(self.course.id),
            'dry-run': is_dry_run
        }
        return self.client.post(self.view_url, data=data)

    def test_force_publish_dry_run(self):
        """
        Test complete flow of force publish as dry run.
        """
        response = self.force_publish_course(is_dry_run='on')
        self.validate_success_from_response(response, _('Following course versions would be changed'))

        # verify that course still has changes as we just dry ran force publish course.
        self.assertTrue(self.store.has_changes(self.store.get_item(self.course.location)))

        # verify that both branch versions are still different
        self.verify_versions_are_different()

    def test_force_publish(self):
        """
        Test complete flow of force publish.
        """
        versions = get_course_versions(unicode(self.course.id))

        response = self.force_publish_course()
        self.validate_success_from_response(response, _('Now published and draft branch have same version'))

        # verify that course has no changes
        self.assertFalse(self.store.has_changes(self.store.get_item(self.course.location)))

        # get new draft and publish branch versions
        updated_versions = get_course_versions(unicode(self.course.id))

        # verify that the draft branch didn't change while the published branch did
        self.assertEqual(versions['draft-branch'], updated_versions['draft-branch'])
        self.assertNotEqual(versions['published-branch'], updated_versions['published-branch'])

        # verify that draft and publish point to same versions now
        self.assertEqual(updated_versions['draft-branch'], updated_versions['published-branch'])
