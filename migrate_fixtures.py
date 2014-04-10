"""
@since: 2014-04-07
@author: Jivan
@brief: Recursively searches current Django project paths for fixtures and migrates each it finds. 
"""
from _collections import defaultdict
import logging
import sys

from django.core.exceptions import ImproperlyConfigured
from south.models import MigrationHistory

import simplejson as json


# check out latest code
# syncdb --all
# fake all migrations (this is a hack for our project which won't migrate forward from 0001_initial)
# extract latest south migrations from fixture
# migrate to latest migrations in fixture
# load fixture
# migrate to latest migrations in project
# dump fixture
# If fixture doesn't have migration history
# Try loading fixture
# If failed, find commit where fixture last modified
# Collect latest migrations in commit
# Migrate database to latest migrations in commit
# Load fixture
# Migrate fixture
# Dump fixture (now with migration history)
logger = logging.getLogger(__name__)
sh = logging.StreamHandler()
logger.addHandler(sh)

def migrate_fixture(fixture_path, db='fixture_migrator'):
    """ @brief: Uses South migrations in the current project to update the contents of the
            fixture at \a fixture_path.
        @author: Jivan
        @since: 2014-04-08
    """
    # --- Create empty database migrated to latest migrations.
    from django.core.management.commands.flush import Command as FlushCommand
    fc = FlushCommand()
    fc.execute(database=db, interactive=False, verbosity=1)
    logger.info('--- Syncing Database tables to Current Models')
    from south.management.commands.syncdb import Command as SyncDBCommand
    sc = SyncDBCommand()
    sc.execute(migrate_all=True, migrate=False, database=db, interactive=False, verbosity=1)
    logger.info('--- Faking Migrations to Current Latest')
    from south.management.commands.migrate import Command as MigrateCommand
    mc = MigrateCommand()
    mc.execute(all_apps=True, fake=True, database=db, interactive=False, verbosity=0)
 
    # --- Get South Migration History from fixture.
    # Fixture file
    with open(fixture_path, 'r') as ff:
        fixture_contents = json.load(ff)
        fixture_migrations = [
            ( i['fields']['app_name'], i['fields']['migration'] )
                for i in fixture_contents
                if i['model'] == 'south.migrationhistory'
        ]
    if len(fixture_migrations) == 0:
        fixture_migrations = guess_migrations_from_git_repository()

    fixture_latest_migrations = defaultdict(unicode)
    for app, migration in fixture_migrations:
        latest_migration = fixture_latest_migrations[app]
        if latest_migration == '' or migration > latest_migration:
            fixture_latest_migrations[app] = migration
      
    # --- Migrate database to latest migrations in fixture
    logger.info('--- Migrating database backwards to latest migrations in fixture.')
    for app, latest_migration in fixture_latest_migrations.items():
        print('Migrating {} to {}'.format(app, latest_migration))
        try:
            mc.execute(app=app, target=latest_migration, database=db, interactive=False, verbosity=1)
        except ImproperlyConfigured as ex:
            if ex.message == 'App with label {} could not be found'.format(app):
                logger.error("Looks like app '{}' was removed from settings.  "
                             "I'll remove its entries from South's Migration history "
                             "in the new fixture.".format(app))
            MigrationHistory.objects.using(db).filter(app_name=app).delete()
            continue

    # --- Load fixture
    from django.core.management.commands.loaddata import Command as LoadDataCommand
    ldc = LoadDataCommand()
    ldc.execute(fixture_path, database=db, verbosity=1)
    
    # --- Migrate to latest migrations in codebase
    mc.execute(database=db, interactive=False, verbosity=1)
 
    # --- Dump the contents back out to fixture
    from django.core.management.commands.dumpdata import Command as DumpDataCommand
    ddc = DumpDataCommand()
    from cStringIO import StringIO
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    ddc.execute(format='json', indent=4, database=db, exclude=[])
    sys.stdout = old_stdout
    with open(fixture_path, 'w') as f:
        f.write(mystdout.getvalue())
        mystdout.close()

if __name__ == '__main__':
    fixture_path = sys.argv[1]
    migrate_fixture(fixture_path)
