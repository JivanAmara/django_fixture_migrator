"""
@since: 2014-04-07
@author: Jivan
@brief: Recursively searches current Django project paths for fixtures and migrates each it finds. 
"""
from _collections import defaultdict
import logging
import subprocess
import sys
import django

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from south.exceptions import NoMigrations
from south.management.commands.migrate import show_migration_changes
from south.migration.base import Migrations
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

def guess_migrations_from_git_repository(fixture_path):
    """ @brief: Collects the latest migration labels for each app from the commit in which
            \a fixture_path was last updated.
        @author: Jivan
        @since: 2014-04-19
    """
    # --- Get the current git commit
    cmd = ['git', '--no-pager', 'log', '-1', '--pretty=oneline' ]
    cmd = ' '.join(cmd)
 
    o = subprocess.check_output(cmd, shell=True)
    outs = o.split()
    original_commit = outs[0]

    # If anything goes wrong, revert to the original git location
    try:
        # --- Get the commit that \a fixture_path was last modified.
        cmd = ['git', '--no-pager', 'log', '-1', '--pretty=oneline', '--follow {}'.format(fixture_path)]
        cmd = ' '.join(cmd)
     
        o = subprocess.check_output(cmd, shell=True)
        outs = o.split()
        last_modified_commit = outs[0]
     
        # --- Check out that commit.
        cmd = ['git', 'checkout', last_modified_commit]
        cmd = ' '.join(cmd)
        o = subprocess.check_output(cmd, shell=True)
    
        # --- Search apps for migrations
        installed_apps = settings.INSTALLED_APPS
    
        # dictionary with app name as key and latest migration as value
        latest_migrations = dict()
    
        for installed_app in installed_apps:
            try:            
                migrations_for_app = Migrations(installed_app)
            except NoMigrations:
                logger.info('{} has no migrations, skipping'.format(installed_app))
                continue
            except ImproperlyConfigured as ex:
                if ex.message[-27:] == 'missing a models.py module.':
                    logger.info('{}  skipping.'.format(ex.message))
                    continue
                else:
                    raise
    
            latest_migration = migrations_for_app[0]
            for m in migrations_for_app[1:]:
                if m > latest_migration:
                    latest_migration = m
    
            latest_migrations.update({latest_migration.app_label(): latest_migration.name()})
    finally:
        # --- Check out original commit.
        cmd = ['git', 'checkout', original_commit]
        cmd = ' '.join(cmd)
        o = subprocess.check_output(cmd, shell=True)

    return latest_migrations
        
def migrate_fixture(fixture_path, db='fixture_migrator'):
    """ @brief: Uses South migrations in the current project to update the contents of the
            fixture at \a fixture_path.
        @author: Jivan
        @since: 2014-04-08
    """
    # --- Create empty database migrated to latest migrations.
#     from django.core.management.commands.flush import Command as FlushCommand
#     fc = FlushCommand()
#     fc.execute(database=db, interactive=False, verbosity=0)
    logger.info('--- Syncing Database tables to Current Models')
    from south.management.commands.syncdb import Command as SyncDBCommand
    sc = SyncDBCommand()
    sc.execute(migrate_all=True, migrate=False, database=db, interactive=False, verbosity=0)
    logger.info('--- Faking Migrations to Current Latest')
    from south.management.commands.migrate import Command as MigrateCommand
    mc = MigrateCommand()
    mc.execute(all_apps=True, fake=True, database=db, interactive=False, verbosity=0)
 
    # --- Get South Migration History from fixture.
    # Fixture file
    with open(fixture_path, 'r') as ff:
        fixture_contents = json.load(ff)
        fixture_migrations = [
            { i['fields']['app_name']: i['fields']['migration'] }
                for i in fixture_contents
                if i['model'] == 'south.migrationhistory'
        ]
    if len(fixture_migrations) == 0:
        logger.info('No migration history found in fixture, guessing migrations from last commit this fixture was migrated.')
        fixture_migrations = guess_migrations_from_git_repository(fixture_path)

    fixture_latest_migrations = defaultdict(unicode)
    for app, migration in fixture_migrations.items():
        latest_migration = fixture_latest_migrations[app]
        if latest_migration == '' or migration > latest_migration:
            fixture_latest_migrations[app] = migration
      
    # --- Migrate database to latest migrations in fixture
    logger.info('--- Migrating database backwards to latest migrations in fixture.')
    for app, latest_migration in fixture_latest_migrations.items():
        print('Migrating {} to {}'.format(app, latest_migration))
        try:
            mc.execute(app=app, target=latest_migration, database=db, interactive=False, verbosity=0)
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
#     guess_migrations_from_git_repository(fixture_path)
    migrate_fixture(fixture_path)
