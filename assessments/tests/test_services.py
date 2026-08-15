from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from assessments.models import Assessment, Result
from assessments.services import (
    calculate_assessment_statistics,
    calculate_course_grade,
)
from courses.models import Course
from students.models import Student, Enrollment


class CalculateCourseGradeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
        )

    def test_returns_zero_when_student_has_no_results(self):
        grade = calculate_course_grade(self.enrollment)

        self.assertEqual(grade, Decimal("0.00"))

    def test_calculates_weighted_grade_from_completed_assessments(self):
        test = Assessment.objects.create(
            course=self.course,
            name="Test",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        assignment = Assessment.objects.create(
            course=self.course,
            name="Assignment",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )

        Assessment.objects.create(
            course=self.course,
            name="Final Exam",
            max_mark=Decimal("100.00"),
            weight=Decimal("50.00"),
        )

        Result.objects.create(
            assessment=test,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        Result.objects.create(
            assessment=assignment,
            enrollment=self.enrollment,
            mark=Decimal("90.00"),
        )

        grade = calculate_course_grade(self.enrollment)

        self.assertEqual(grade, Decimal("86.00"))

    def test_returns_zero_when_only_completed_assessment_has_zero_weight(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Practice Quiz",
            max_mark=Decimal("10.00"),
            weight=Decimal("0.00"),
        )

        Result.objects.create(
            assessment=assessment,
            enrollment=self.enrollment,
            mark=Decimal("10.00"),
        )

        grade = calculate_course_grade(self.enrollment)

        self.assertEqual(grade, Decimal("0.00"))

    def test_rounds_grade_to_two_decimal_places(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test",
            max_mark=Decimal("3.00"),
            weight=Decimal("100.00"),
        )

        Result.objects.create(
            assessment=assessment,
            enrollment=self.enrollment,
            mark=Decimal("2.00"),
        )

        grade = calculate_course_grade(self.enrollment)

        self.assertEqual(grade, Decimal("66.67"))


class AssessmentStatisticsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

    def test_calculates_assessment_statistics(self):
        marks = [
            Decimal("40.00"),
            Decimal("25.00"),
            Decimal("45.00"),
        ]

        for index, mark in enumerate(marks):
            student = Student.objects.create(
                owner=self.user,
                student_number=f"1000000{index}",
                first_name="Student",
                last_name=str(index),
                email=f"student{index}@example.com",
            )

            enrollment = Enrollment.objects.create(
                course=self.course,
                student=student,
            )

            Result.objects.create(
                assessment=self.assessment,
                enrollment=enrollment,
                mark=mark,
            )

        statistics = calculate_assessment_statistics(
            self.assessment
        )

        self.assertEqual(statistics["graded_count"], 3)
        self.assertEqual(
            statistics["average_percentage"],
            Decimal("73.33"),
        )
        self.assertEqual(
            statistics["minimum_percentage"],
            Decimal("50.00"),
        )
        self.assertEqual(
            statistics["maximum_percentage"],
            Decimal("90.00"),
        )

    def test_returns_zero_statistics_when_assessment_has_no_results(self):
        statistics = calculate_assessment_statistics(
            self.assessment
        )

        self.assertEqual(statistics["graded_count"], 0)
        self.assertEqual(
            statistics["average_percentage"],
            Decimal("0.00"),
        )
        self.assertEqual(
            statistics["minimum_percentage"],
            Decimal("0.00"),
        )
        self.assertEqual(
            statistics["maximum_percentage"],
            Decimal("0.00"),
        )