import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
from django.contrib.postgres.operations import BtreeGistExtension
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('capacity', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
                'constraints': [models.CheckConstraint(condition=models.Q(('capacity__gt', 0)), name='room_capacity_positive')],
            },
        ),
        migrations.CreateModel(
            name='Reservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_at', models.DateTimeField()),
                ('end_at', models.DateTimeField()),
                ('attendees_count', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('status', models.CharField(choices=[('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')], default='confirmed', max_length=9)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reservations', to=settings.AUTH_USER_MODEL)),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reservations', to='reservations.room')),
            ],
            options={
                'ordering': ['-start_at', '-pk'],
                'constraints': [models.CheckConstraint(condition=models.Q(('attendees_count__gt', 0)), name='reservation_attendees_positive'), models.CheckConstraint(condition=models.Q(('end_at__gt', models.F('start_at'))), name='reservation_time_order'), models.CheckConstraint(condition=models.Q(models.Q(('cancelled_at__isnull', True), ('status', 'confirmed')), models.Q(('cancelled_at__isnull', False), ('status', 'cancelled')), _connector='OR'), name='reservation_valid_state'), django.contrib.postgres.constraints.ExclusionConstraint(condition=models.Q(('status', 'confirmed')), expressions=[('room', '='), (models.Func('start_at', 'end_at', django.contrib.postgres.fields.ranges.RangeBoundary(), function='TSTZRANGE', output_field=django.contrib.postgres.fields.ranges.DateTimeRangeField()), '&&')], name='reservation_no_overlap')],
            },
        ),
    ]
