import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReservationRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=255)),
                ('request_hash', models.CharField(max_length=64)),
                ('response_body', models.JSONField(null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reservation', models.OneToOneField(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='creation_request', to='reservations.reservation')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('user', 'key'), name='reservation_request_user_key'), models.CheckConstraint(condition=models.Q(models.Q(('reservation__isnull', True), ('response_body__isnull', True)), models.Q(('reservation__isnull', False), ('response_body__isnull', False)), _connector='OR'), name='reservation_request_response_pair')],
            },
        ),
    ]
