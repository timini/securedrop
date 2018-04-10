# -*- coding: utf-8 -*-
import os
import io
import pytest
import re
import shutil
import store
import unittest
import zipfile

from flask import current_app

os.environ['SECUREDROP_ENV'] = 'test'  # noqa
from sdconfig import config
import journalist_app
import utils

from store import Storage


def create_file_in_source_dir(config, filesystem_id, filename):
    """Helper function for simulating files"""
    source_directory = os.path.join(config.STORE_DIR,
                                    filesystem_id)
    os.makedirs(source_directory)

    file_path = os.path.join(source_directory, filename)
    with io.open(file_path, 'a'):
        os.utime(file_path, None)

    return source_directory, file_path


def test_path_returns_filename_of_folder(journalist_app, config):
    """`Storage.path` is called in this way in
        journalist.delete_collection
    """
    filesystem_id = 'example'
    generated_absolute_path = journalist_app.storage.path(filesystem_id)

    expected_absolute_path = os.path.join(config.STORE_DIR, filesystem_id)
    assert generated_absolute_path == expected_absolute_path


def test_path_returns_filename_of_items_within_folder(journalist_app, config):
    """`Storage.path` is called in this way in journalist.bulk_delete"""
    filesystem_id = 'example'
    item_filename = '1-quintuple_cant-msg.gpg'
    generated_absolute_path = journalist_app.storage.path(filesystem_id,
                                                          item_filename)

    expected_absolute_path = os.path.join(config.STORE_DIR,
                                          filesystem_id, item_filename)
    assert generated_absolute_path == expected_absolute_path


def test_verify_path_not_absolute(journalist_app, config):
    with pytest.raises(store.PathException):
        journalist_app.storage.verify(
            os.path.join(config.STORE_DIR, '..', 'etc', 'passwd'))


def test_verify_in_store_dir(journalist_app, config):
    with pytest.raises(store.PathException) as e:
        journalist_app.storage.verify(config.STORE_DIR + "_backup")

    assert 'Invalid directory' in str(e)


def test_verify_store_path_not_absolute(journalist_app):
    with pytest.raises(store.PathException) as e:
        journalist_app.storage.verify('..')

    assert 'The path is not absolute and/or normalized' in str(e)


def test_verify_store_dir_not_absolute():
    with pytest.raises(store.PathException) as exc_info:
        Storage('..', '/', '<not a gpg key>')

    msg = str(exc_info.value)
    assert re.compile('storage_path.*is not absolute').match(msg)


def test_verify_store_temp_dir_not_absolute():
    with pytest.raises(store.PathException) as exc_info:
        Storage('/', '..', '<not a gpg key>')

    msg = str(exc_info.value)
    assert re.compile('temp_dir.*is not absolute').match(msg)


def test_verify_flagged_file_in_sourcedir_returns_true(journalist_app, config):
    source_directory, file_path = create_file_in_source_dir(
        config, 'example-filesystem-id', '_FLAG'
    )

    assert journalist_app.storage.verify(file_path)


class TestStore(unittest.TestCase):

    """The set of tests for store.py."""

    def setUp(self):
        self.__context = journalist_app.create_app(config).app_context()
        self.__context.push()
        utils.env.setup()

    def tearDown(self):
        utils.env.teardown()
        self.__context.pop()

    def create_file_in_source_dir(self, filesystem_id, filename):
        """Helper function for simulating files"""
        source_directory = os.path.join(config.STORE_DIR,
                                        filesystem_id)
        os.makedirs(source_directory)

        file_path = os.path.join(source_directory, filename)
        with io.open(file_path, 'a'):
            os.utime(file_path, None)

        return source_directory, file_path

    def test_verify_invalid_file_extension_in_sourcedir_raises_exception(self):
        source_directory, file_path = self.create_file_in_source_dir(
            'example-filesystem-id', 'not_valid.txt'
        )

        with self.assertRaisesRegexp(
                store.PathException,
                'Invalid file extension .txt'):
            current_app.storage.verify(file_path)

        shutil.rmtree(source_directory)  # Clean up created files

    def test_verify_invalid_filename_in_sourcedir_raises_exception(self):
        source_directory, file_path = self.create_file_in_source_dir(
            'example-filesystem-id', 'NOTVALID.gpg'
        )

        with self.assertRaisesRegexp(
                store.PathException,
                'Invalid filename NOTVALID.gpg'):
            current_app.storage.verify(file_path)

        shutil.rmtree(source_directory)  # Clean up created files

    def test_get_zip(self):
        source, _ = utils.db_helper.init_source()
        submissions = utils.db_helper.submit(source, 2)
        filenames = [os.path.join(config.STORE_DIR,
                                  source.filesystem_id,
                                  submission.filename)
                     for submission in submissions]

        archive = zipfile.ZipFile(
            current_app.storage.get_bulk_archive(submissions))
        archivefile_contents = archive.namelist()

        for archived_file, actual_file in zip(archivefile_contents, filenames):
            actual_file_content = io.open(actual_file, 'rb').read()
            zipped_file_content = archive.read(archived_file)
            self.assertEquals(zipped_file_content, actual_file_content)

    def test_rename_valid_submission(self):
        source, _ = utils.db_helper.init_source()
        old_journalist_filename = source.journalist_filename
        old_filename = utils.db_helper.submit(source, 1)[0].filename
        new_journalist_filename = 'nestor_makhno'
        expected_filename = old_filename.replace(old_journalist_filename,
                                                 new_journalist_filename)
        actual_filename = current_app.storage.rename_submission(
            source.filesystem_id, old_filename,
            new_journalist_filename)
        self.assertEquals(actual_filename, expected_filename)

    def test_rename_submission_with_invalid_filename(self):
        original_filename = '1-quintuple_cant-msg.gpg'
        returned_filename = current_app.storage.rename_submission(
                'example-filesystem-id', original_filename,
                'this-new-filename-should-not-be-returned')

        # None of the above files exist, so we expect the attempt to rename
        # the submission to fail and the original filename to be returned.
        self.assertEquals(original_filename, returned_filename)
