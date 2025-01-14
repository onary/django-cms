# Generated by Django 1.11.13 on 2018-08-08 14:26
from __future__ import unicode_literals

from cms.models import PageContent
from cms.utils.conf import get_cms_setting
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0028_remove_page_placeholders'),
    ]

    operations = [
        migrations.AddField(
            model_name='title',
            name='changed_by',
            field=models.CharField(editable=False, default='', max_length=255, verbose_name='changed by'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='title',
            name='changed_date',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='title',
            name='created_by',
            field=models.CharField(editable=False, default='', max_length=255, verbose_name='created by'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='title',
            name='in_navigation',
            field=models.BooleanField(db_index=True, default=True, verbose_name='in navigation'),
        ),
        migrations.AddField(
            model_name='title',
            name='limit_visibility_in_menu',
            field=models.SmallIntegerField(blank=True, choices=PageContent.LIMIT_VISIBILITY_IN_MENU_CHOICES, db_index=True, default=None, help_text='limit when this page is visible in the menu', null=True, verbose_name='menu visibility'),
        ),
        migrations.AddField(
            model_name='title',
            name='template',
            field=models.CharField(choices=PageContent.template_choices, default=PageContent.TEMPLATE_DEFAULT, help_text='The template used to render the content.', max_length=100, verbose_name='template'),
        ),
        migrations.AddField(
            model_name='title',
            name='xframe_options',
            field=models.IntegerField(choices=PageContent.X_FRAME_OPTIONS_CHOICES, default=get_cms_setting('DEFAULT_X_FRAME_OPTIONS'), verbose_name="X Frame Options"),
        ),
        migrations.AddField(
            model_name='title',
            name='soft_root',
            field=models.BooleanField(db_index=True, default=False, help_text='All ancestors will not be displayed in the navigation', verbose_name='soft root'),
        ),
        migrations.CreateModel(
            name='PageUrl',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=255, verbose_name='slug')),
                ('path', models.CharField(db_index=True, max_length=255, null=True, verbose_name='Path')),
                ('language', models.CharField(db_index=True, max_length=15, verbose_name='language')),
                ('managed', models.BooleanField(default=False)),
                ('page',
                 models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='urls', to='cms.Page',
                                   verbose_name='page')),
            ],
            options={
                'default_permissions': [],
            },
        ),
    ]
