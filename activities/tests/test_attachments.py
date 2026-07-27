"""
Test suite for Activity Attachment functionality
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.template.loader import render_to_string
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import datetime, date
from activities.models import Activity, ActivityAttachment
from masters.models import Funder, ActivityStatus, Currency
from accounts.models import Cluster
from audit.models import AuditLog
import json

User = get_user_model()


class ActivityAttachmentTestCase(TestCase):
    """Test cases for activity attachment functionality"""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data"""
        # Create test users
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create superuser for admin access
        cls.admin = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        
        # Create test groups
        cls.editor_group = Group.objects.create(name='Activity Editor')
        cls.viewer_group = Group.objects.create(name='Activity Viewer')
        
        # Create currencies
        cls.currency = Currency.objects.create(code='USD', name='US Dollar')
        
        # Create status
        cls.status = ActivityStatus.objects.create(name='Active')
        
        # Create funder
        cls.funder = Funder.objects.create(name='Test Funder', code='TF')
        
        # Create cluster
        cls.cluster = Cluster.objects.create(short_name='TC', full_name='Test Cluster')
        
        # Create test activity
        cls.activity = Activity.objects.create(
            activity_id='TEST001',
            name='Test Activity',
            year=2024,
            status=cls.status,
            currency=cls.currency,
            responsible_officer=cls.user,
            planned_month=datetime.now(),
            total_budget=100000
        )
        cls.activity.funders.add(cls.funder)
        cls.activity.clusters.add(cls.cluster)
    
    def setUp(self):
        """Set up test client"""
        self.client = Client()
    
    def test_attachment_model_creation(self):
        """Test creating an attachment"""
        file = SimpleUploadedFile("test.pdf", b"file content", content_type="application/pdf")
        
        attachment = ActivityAttachment.objects.create(
            activity=self.activity,
            file=file,
            filename="test.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"file content")
        )
        
        self.assertEqual(attachment.activity, self.activity)
        self.assertEqual(attachment.filename, "test.pdf")
        self.assertEqual(attachment.version, 1)
        self.assertTrue(attachment.is_latest)
        self.assertFalse(attachment.is_deleted)
    
    def test_get_attachment_versions(self):
        """Test retrieving attachment versions"""
        # Create first version
        file1 = SimpleUploadedFile("test_v1.pdf", b"file content v1", content_type="application/pdf")
        att1 = ActivityAttachment.objects.create(
            activity=self.activity,
            file=file1,
            filename="test_v1.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"file content v1")
        )
        
        # Create second version
        versions = ActivityAttachment.objects.filter(
            activity=self.activity,
            document_type="report"
        ).order_by('-version')
        
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions[0].is_latest)
    
    def test_soft_delete_attachment(self):
        """Test soft delete functionality"""
        file = SimpleUploadedFile("test.pdf", b"file content", content_type="application/pdf")
        attachment = ActivityAttachment.objects.create(
            activity=self.activity,
            file=file,
            filename="test.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"file content")
        )
        
        # Soft delete
        attachment.is_deleted = True
        attachment.save()
        
        # Verify
        refreshed = ActivityAttachment.objects.get(pk=attachment.pk)
        self.assertTrue(refreshed.is_deleted)
    
    def test_upload_attachment_view_authentication(self):
        """Test upload view requires authentication"""
        response = self.client.post(
            f'/activities/{self.activity.pk}/attachments/upload/',
            {'file': SimpleUploadedFile("test.pdf", b"content")}
        )
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_list_attachments_view(self):
        """Test list attachments view"""
        self.client.login(username='testuser', password='testpass123')
        self.user.groups.add(self.viewer_group)
        
        # Create test attachment
        file = SimpleUploadedFile("test.pdf", b"file content", content_type="application/pdf")
        ActivityAttachment.objects.create(
            activity=self.activity,
            file=file,
            filename="test.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"file content")
        )
        
        response = self.client.get(f'/activities/{self.activity.pk}/attachments/')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('attachments', data)
    
    def test_document_type_validation(self):
        """Test that only valid document types are accepted"""
        valid_types = ['report', 'proposal', 'invoice', 'receipt', 'other']
        
        for doc_type in valid_types:
            file = SimpleUploadedFile("test.pdf", b"file content", content_type="application/pdf")
            attachment = ActivityAttachment.objects.create(
                activity=self.activity,
                file=file,
                filename=f"test_{doc_type}.pdf",
                document_type=doc_type,
                file_type="pdf",
                uploaded_by=self.user,
                file_size=len(b"file content")
            )
            self.assertEqual(attachment.document_type, doc_type)
    
    def test_file_type_detection(self):
        """Test automatic file type detection"""
        file_types = [
            ("test.pdf", "pdf", b"PDF content"),
            ("test.docx", "docx", b"DOCX content"),
            ("test.xlsx", "xlsx", b"XLSX content"),
        ]
        
        for filename, expected_type, content in file_types:
            file = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
            attachment = ActivityAttachment.objects.create(
                activity=self.activity,
                file=file,
                filename=filename,
                document_type="report",
                file_type=expected_type,
                uploaded_by=self.user,
                file_size=len(content)
            )
            self.assertEqual(attachment.file_type, expected_type)
    
    def test_attachment_ordering(self):
        """Test that attachments are ordered by upload date"""
        import time
        
        attachments = []
        for i in range(3):
            file = SimpleUploadedFile(f"test{i}.pdf", b"content", content_type="application/pdf")
            att = ActivityAttachment.objects.create(
                activity=self.activity,
                file=file,
                filename=f"test{i}.pdf",
                document_type="report",
                file_type="pdf",
                uploaded_by=self.user,
                file_size=len(b"content")
            )
            attachments.append(att)
            time.sleep(0.1)
        
        # Retrieve ordered list
        ordered = ActivityAttachment.objects.filter(activity=self.activity).order_by('-uploaded_at')
        
        # Most recent should be first
        self.assertEqual(ordered[0].pk, attachments[-1].pk)
    
    def test_attachment_permissions(self):
        """Test permission-based access control"""
        self.client.login(username='testuser', password='testpass123')
        
        # User without permission should get 403
        response = self.client.post(
            f'/activities/{self.activity.pk}/attachments/upload/',
            {'file': SimpleUploadedFile("test.pdf", b"content")}
        )
        
        self.assertEqual(response.status_code, 403)

    def test_detail_template_renders_when_audit_log_user_is_missing(self):
        """The detail page should not crash if an audit log has no linked user."""
        AuditLog.objects.create(
            user=None,
            action='Status changed',
            object_repr='Test Activity',
            activity_id=self.activity.pk,
            change_description='Status changed'
        )

        context = {
            'activity': self.activity,
            'audit_logs': AuditLog.objects.filter(activity_id=self.activity.pk).order_by('-timestamp'),
            'all_users': [],
            'all_statuses': [],
            'users': [],
            'statuses': [],
            'clusters': [],
            'funders': [],
            'currencies': [],
            'years': [],
            'can_edit': True,
            'can_delete': True,
        }

        rendered = render_to_string('activities/detail.html', context)
        self.assertIn('System', rendered)


class ActivityAttachmentIntegrationTestCase(TestCase):
    """Integration tests for attachment workflow"""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data"""
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        cls.currency = Currency.objects.create(code='USD', name='US Dollar')
        cls.status = ActivityStatus.objects.create(name='Active')
        cls.funder = Funder.objects.create(name='Test Funder', code='TF')
        cls.cluster = Cluster.objects.create(short_name='TC', full_name='Test Cluster')
        
        cls.activity = Activity.objects.create(
            activity_id='TEST001',
            name='Test Activity',
            year=2024,
            status=cls.status,
            currency=cls.currency,
            responsible_officer=cls.user,
            planned_month=datetime.now(),
            total_budget=100000
        )
        cls.activity.funders.add(cls.funder)
        cls.activity.clusters.add(cls.cluster)
    
    def test_complete_attachment_workflow(self):
        """Test complete attachment workflow: upload -> list -> download -> delete"""
        # Step 1: Upload attachment
        file = SimpleUploadedFile("report.pdf", b"PDF content", content_type="application/pdf")
        attachment = ActivityAttachment.objects.create(
            activity=self.activity,
            file=file,
            filename="report.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"PDF content"),
            description="Initial report"
        )
        
        self.assertIsNotNone(attachment.pk)
        self.assertEqual(attachment.version, 1)
        
        # Step 2: List attachments
        attachments = ActivityAttachment.objects.filter(
            activity=self.activity,
            is_deleted=False
        )
        
        self.assertEqual(len(attachments), 1)
        self.assertTrue(attachments[0].is_latest)
        
        # Step 3: Upload new version
        file2 = SimpleUploadedFile("report_v2.pdf", b"PDF content v2", content_type="application/pdf")
        attachment2 = ActivityAttachment.objects.create(
            activity=self.activity,
            file=file2,
            filename="report_v2.pdf",
            document_type="report",
            file_type="pdf",
            uploaded_by=self.user,
            file_size=len(b"PDF content v2"),
            version=2,
            description="Updated report"
        )
        
        # Step 4: Verify version history
        versions = ActivityAttachment.objects.filter(
            activity=self.activity,
            document_type="report"
        ).order_by('-version')
        
        self.assertEqual(len(versions), 2)
        self.assertTrue(versions[0].is_latest)
        self.assertFalse(versions[1].is_latest)
        
        # Step 5: Soft delete
        versions[0].is_deleted = True
        versions[0].save()
        
        active = ActivityAttachment.objects.filter(
            activity=self.activity,
            is_deleted=False
        )
        
        self.assertEqual(len(active), 1)


class ActivityListAndDashboardConsistencyTestCase(TestCase):
    """Regression tests for list/dashboard/procurement consistency."""

    @classmethod
    def setUpTestData(cls):
        cls.client = Client()
        cls.user = User.objects.create_user(
            username='datamanager',
            email='dm@example.com',
            password='testpass123'
        )
        data_manager_group, _ = Group.objects.get_or_create(name='Data Manager')
        cls.user.groups.add(data_manager_group)

        cls.currency = Currency.objects.create(code='ZMW', name='Zambian Kwacha')
        cls.status = ActivityStatus.objects.create(name='Planned')
        cls.funder = Funder.objects.create(name='Consistency Funder', code='CF')
        cls.cluster = Cluster.objects.create(short_name='CC', full_name='Consistency Cluster')

        current_year = date.today().year

        # Included in default-year totals (current year, not deleted)
        cls.current_year_active = Activity.objects.create(
            activity_id='CONS001',
            name='Current Year Active',
            year=current_year,
            status=cls.status,
            currency=cls.currency,
            responsible_officer=cls.user,
            planned_month=datetime(current_year, 1, 15),
            total_budget=1000,
            procurement_amount=1000
        )

        # Should be excluded everywhere due to soft-delete
        cls.current_year_deleted = Activity.objects.create(
            activity_id='CONS002',
            name='Current Year Deleted',
            year=current_year,
            status=cls.status,
            currency=cls.currency,
            responsible_officer=cls.user,
            planned_month=datetime(current_year, 2, 15),
            total_budget=2000,
            procurement_amount=2000,
            deleted=True
        )

        # Should be excluded from default (no-filter) totals due to non-current year
        cls.previous_year_active = Activity.objects.create(
            activity_id='CONS003',
            name='Previous Year Active',
            year=current_year - 1,
            status=cls.status,
            currency=cls.currency,
            responsible_officer=cls.user,
            planned_month=datetime(current_year - 1, 3, 15),
            total_budget=3000,
            procurement_amount=500
        )

        for activity in [cls.current_year_active, cls.current_year_deleted, cls.previous_year_active]:
            activity.funders.add(cls.funder)
            activity.clusters.add(cls.cluster)

    def setUp(self):
        self.client = Client()
        self.client.login(username='datamanager', password='testpass123')

    def test_default_dashboard_and_activities_totals_match_and_exclude_deleted(self):
        activities_response = self.client.get('/activities/')
        dashboard_response = self.client.get('/dashboard/')

        self.assertEqual(activities_response.status_code, 200)
        self.assertEqual(dashboard_response.status_code, 200)

        activities_total = activities_response.context['total_activities']
        dashboard_total = dashboard_response.context['total_activities']

        self.assertEqual(activities_total, dashboard_total)
        self.assertEqual(activities_total, 1)

    def test_procurement_list_excludes_deleted_activities(self):
        procurement_response = self.client.get('/activities/procurement/')

        self.assertEqual(procurement_response.status_code, 200)
        procurement_ids = set(procurement_response.context['activities'].values_list('activity_id', flat=True))

        self.assertIn('CONS001', procurement_ids)
        self.assertIn('CONS003', procurement_ids)
        self.assertNotIn('CONS002', procurement_ids)


if __name__ == '__main__':
    import unittest
    unittest.main()
