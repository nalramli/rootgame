import django.db.models.deletion
from django.db import migrations, models


def copy_mood_to_state(apps, schema_editor):
    CurrentMood = apps.get_model("game", "CurrentMood")
    RatsPlayerState = apps.get_model("game", "RatsPlayerState")
    for mood in CurrentMood.objects.select_related("player").all():
        state = RatsPlayerState.objects.filter(player=mood.player).first()
        if state is not None:
            state.mood_type = mood.mood_type
            state.save()


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0038_alter_gamelog_log_type"),
    ]

    operations = [
        # 1. Add mood_type to RatsPlayerState (nullable while copying data)
        migrations.AddField(
            model_name="ratsplayerstate",
            name="mood_type",
            field=models.CharField(
                blank=True,
                max_length=10,
                null=True,
            ),
        ),
        # 2. Copy mood data from CurrentMood
        migrations.RunPython(copy_mood_to_state, migrations.RunPython.noop),
        # 3. Make mood_type non-nullable with default
        migrations.AlterField(
            model_name="ratsplayerstate",
            name="mood_type",
            field=models.CharField(
                choices=[
                    ("bitter", "Bitter"),
                    ("grandiose", "Grandiose"),
                    ("jubilant", "Jubilant"),
                    ("lavish", "Lavish"),
                    ("relentless", "Relentless"),
                    ("rowdy", "Rowdy"),
                    ("stubborn", "Stubborn"),
                    ("wrathful", "Wrathful"),
                ],
                default="stubborn",
                max_length=10,
            ),
        ),
        # 4. Drop CurrentMood
        migrations.DeleteModel(
            name="CurrentMood",
        ),
    ]
