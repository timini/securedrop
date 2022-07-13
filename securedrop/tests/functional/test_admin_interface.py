import logging
import time
from pathlib import Path
from typing import Callable, Generator, Tuple
from uuid import uuid4

import pytest
from models import Journalist
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions
from tests.functional import functional_test as ft
from tests.functional import journalist_navigation_steps, source_navigation_steps
from tests.functional.app_navigators import JournalistAppNavigator
from tests.functional.conftest import SdServersFixtureResult, spawn_sd_servers
from tests.functional.db_session import get_database_session
from tests.functional.factories import SecureDropConfigFactory
from tests.functional.sd_config_v2 import SecureDropConfig


class TestAdminInterfaceAddUser:
    def test_admin_adds_non_admin_user(self, sd_servers_v2_with_clean_state, firefox_web_driver):
        # Given an SD server
        # And a journalist logged into the journalist interface as an admin
        journ_app_nav = JournalistAppNavigator(
            journalist_app_base_url=sd_servers_v2_with_clean_state.journalist_app_base_url,
            web_driver=firefox_web_driver,
        )
        assert sd_servers_v2_with_clean_state.journalist_is_admin
        journ_app_nav.journalist_logs_in(
            username=sd_servers_v2_with_clean_state.journalist_username,
            password=sd_servers_v2_with_clean_state.journalist_password,
            otp_secret=sd_servers_v2_with_clean_state.journalist_otp_secret,
        )

        # Then they see the same interface as a normal user, since there may be users who wish to
        # be both journalists and admins
        assert journ_app_nav.is_on_journalist_homepage()

        # And they see a link that take them to the admin page
        assert journ_app_nav.journalist_sees_link_to_admin_page()

        # And when they go to the admin page to add a new non-admin user
        journ_app_nav.admin_visits_admin_interface()
        result = journ_app_nav.admin_creates_a_user(is_admin=False)
        new_user_username, new_user_pw, new_user_otp_secret = result

        # Then it succeeds

        # Log the admin user out
        journ_app_nav.journalist_logs_out()
        journ_app_nav.nav_helper.wait_for(
            lambda: journ_app_nav.driver.find_element_by_css_selector(".login-form")
        )

        # And when the new user tries to login
        journ_app_nav.journalist_logs_in(
            username=new_user_username,
            password=new_user_pw,
            otp_secret=new_user_otp_secret,
        )

        # It succeeds
        # And since the new user is not an admin, they don't see a link to the admin page
        assert not journ_app_nav.journalist_sees_link_to_admin_page()

    def test_admin_adds_admin_user(self, sd_servers_v2_with_clean_state, firefox_web_driver):
        # Given an SD server
        # And the first journalist logged into the journalist interface as an admin
        journ_app_nav = JournalistAppNavigator(
            journalist_app_base_url=sd_servers_v2_with_clean_state.journalist_app_base_url,
            web_driver=firefox_web_driver,
        )
        assert sd_servers_v2_with_clean_state.journalist_is_admin
        journ_app_nav.journalist_logs_in(
            username=sd_servers_v2_with_clean_state.journalist_username,
            password=sd_servers_v2_with_clean_state.journalist_password,
            otp_secret=sd_servers_v2_with_clean_state.journalist_otp_secret,
        )

        # When they go to the admin page to add a new admin user
        journ_app_nav.admin_visits_admin_interface()
        result = journ_app_nav.admin_creates_a_user(is_admin=True)
        new_user_username, new_user_pw, new_user_otp_secret = result

        # Then it succeeds

        # Log the admin user out
        journ_app_nav.journalist_logs_out()
        journ_app_nav.nav_helper.wait_for(
            lambda: journ_app_nav.driver.find_element_by_css_selector(".login-form")
        )

        # And when the new user tries to login
        journ_app_nav.journalist_logs_in(
            username=new_user_username,
            password=new_user_pw,
            otp_secret=new_user_otp_secret,
        )

        # It succeeds
        # And since the new user is an admin, they see a link to the admin page
        assert journ_app_nav.journalist_sees_link_to_admin_page()

    def test_admin_adds_user_with_invalid_username(
        self, sd_servers_v2_with_clean_state, firefox_web_driver
    ):
        # Given an SD server
        # And the first journalist logged into the journalist interface as an admin
        journ_app_nav = JournalistAppNavigator(
            journalist_app_base_url=sd_servers_v2_with_clean_state.journalist_app_base_url,
            web_driver=firefox_web_driver,
        )
        assert sd_servers_v2_with_clean_state.journalist_is_admin
        journ_app_nav.journalist_logs_in(
            username=sd_servers_v2_with_clean_state.journalist_username,
            password=sd_servers_v2_with_clean_state.journalist_password,
            otp_secret=sd_servers_v2_with_clean_state.journalist_otp_secret,
        )

        # When they go to the admin page to add a new admin user with ann invalid name
        journ_app_nav.admin_visits_admin_interface()
        journ_app_nav.admin_creates_a_user(
            username="deleted", is_user_creation_expected_to_succeed=False
        )

        # Then it fails
        error_msg = journ_app_nav.nav_helper.wait_for(
            lambda: journ_app_nav.driver.find_element_by_css_selector(".form-validation-error")
        )

        # And they see the corresponding error message
        assert (
            "This username is invalid because it is reserved for internal use "
            "by the software." in error_msg.text
        )


# Tests for editing a user need a second journalist user to be created
_SECOND_JOURNALIST_USERNAME = "second_journalist"
_SECOND_JOURNALIST_PASSWORD = "shivering reliance sadness crinkly landmass wafer deceit"
_SECOND_JOURNALIST_OTP_SECRET = "TVWT452VLMS7KAVZ"


def _create_second_journalist(config_in_use: SecureDropConfig) -> None:
    # Add a test journalist
    with get_database_session(database_uri=config_in_use.DATABASE_URI) as db_session_for_sd_servers:
        journalist = Journalist(
            username=_SECOND_JOURNALIST_USERNAME,
            password=_SECOND_JOURNALIST_PASSWORD,
            is_admin=False,
        )
        journalist.otp_secret = _SECOND_JOURNALIST_OTP_SECRET
        db_session_for_sd_servers.add(journalist)
        db_session_for_sd_servers.commit()


@pytest.fixture(scope="function")
def sd_servers_v2_with_second_journalist(
    setup_journalist_key_and_gpg_folder: Tuple[str, Path]
) -> Generator[SdServersFixtureResult, None, None]:
    """Sams as sd_servers_v2 but spawns the apps with an already-created second journalist.

    Slower than sd_servers_v2 as it is function-scoped.
    """
    default_config = SecureDropConfigFactory.create(
        SECUREDROP_DATA_ROOT=Path(f"/tmp/sd-tests/functional-with-second-journnalist-{uuid4()}"),
    )

    # Ensure the GPG settings match the one in the config to use, to ensure consistency
    journalist_key_fingerprint, gpg_dir = setup_journalist_key_and_gpg_folder
    assert Path(default_config.GPG_KEY_DIR) == gpg_dir
    assert default_config.JOURNALIST_KEY == journalist_key_fingerprint

    # Spawn the apps in separate processes with a callback to create a submission
    with spawn_sd_servers(
        config_to_use=default_config, journalist_app_setup_callback=_create_second_journalist
    ) as sd_servers_result:
        yield sd_servers_result


class TestAdminInterfaceEditAndDeleteUser:
    @staticmethod
    def _admin_logs_in_and_goes_to_edit_page_for_second_journalist(
        sd_servers_result: SdServersFixtureResult,
        firefox_web_driver: WebDriver,
    ) -> JournalistAppNavigator:
        # Log in as the admin
        journ_app_nav = JournalistAppNavigator(
            journalist_app_base_url=sd_servers_result.journalist_app_base_url,
            web_driver=firefox_web_driver,
        )
        assert sd_servers_result.journalist_is_admin
        journ_app_nav.journalist_logs_in(
            username=sd_servers_result.journalist_username,
            password=sd_servers_result.journalist_password,
            otp_secret=sd_servers_result.journalist_otp_secret,
        )

        journ_app_nav.admin_visits_admin_interface()

        # Go to the "edit user" page for the second journalist
        selector = f'a.edit-user[data-username="{_SECOND_JOURNALIST_USERNAME}"]'
        new_user_edit_links = journ_app_nav.driver.find_elements_by_css_selector(selector)
        assert len(new_user_edit_links) == 1
        new_user_edit_links[0].click()

        # Ensure the admin is allowed to edit the second journalist
        def can_edit_user():
            h = journ_app_nav.driver.find_elements_by_tag_name("h1")[0]
            assert f'Edit user "{_SECOND_JOURNALIST_USERNAME}"' == h.text

        journ_app_nav.nav_helper.wait_for(can_edit_user)

        return journ_app_nav

    def test_admin_edits_username(self, sd_servers_v2_with_second_journalist, firefox_web_driver):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        # And they went to the "edit user" page for the second journalist
        journ_app_nav = self._admin_logs_in_and_goes_to_edit_page_for_second_journalist(
            sd_servers_result=sd_servers_v2_with_second_journalist,
            firefox_web_driver=firefox_web_driver,
        )

        # When they change the second journalist's username
        self._admin_edits_username_and_submits_form(journ_app_nav, new_username="new_name")

        # Then it succeeds
        def user_edited():
            flash_msg = journ_app_nav.driver.find_element_by_css_selector(".flash")
            assert "Account updated." in flash_msg.text

        journ_app_nav.nav_helper.wait_for(user_edited)

    def test_admin_edits_invalid_username(
        self, sd_servers_v2_with_second_journalist, firefox_web_driver
    ):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        # And they went to the "edit user" page for the second journalist
        journ_app_nav = self._admin_logs_in_and_goes_to_edit_page_for_second_journalist(
            sd_servers_result=sd_servers_v2_with_second_journalist,
            firefox_web_driver=firefox_web_driver,
        )

        # When they change the second journalist's username to an invalid username
        self._admin_edits_username_and_submits_form(journ_app_nav, new_username="deleted")

        # Then it fails
        def user_edited():
            flash_msg = journ_app_nav.driver.find_element_by_css_selector(".flash")
            assert "Invalid username" in flash_msg.text

        journ_app_nav.nav_helper.wait_for(user_edited)

    @staticmethod
    def _admin_edits_username_and_submits_form(
        journ_app_nav: JournalistAppNavigator,
        new_username: str,
    ) -> None:
        journ_app_nav.nav_helper.safe_send_keys_by_css_selector(
            'input[name="username"]', Keys.CONTROL + "a"
        )
        journ_app_nav.nav_helper.safe_send_keys_by_css_selector(
            'input[name="username"]', Keys.DELETE
        )
        journ_app_nav.nav_helper.safe_send_keys_by_css_selector(
            'input[name="username"]', new_username
        )
        journ_app_nav.nav_helper.safe_click_by_css_selector("button[type=submit]")

    def test_admin_resets_password(self, sd_servers_v2_with_second_journalist, firefox_web_driver):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        # And they went to the "edit user" page for the second journalist
        journ_app_nav = self._admin_logs_in_and_goes_to_edit_page_for_second_journalist(
            sd_servers_result=sd_servers_v2_with_second_journalist,
            firefox_web_driver=firefox_web_driver,
        )

        # When they reset the second journalist's password
        new_password = journ_app_nav.driver.find_element_by_css_selector("#password").text.strip()
        assert new_password
        reset_pw_btn = journ_app_nav.driver.find_element_by_css_selector("#reset-password")
        reset_pw_btn.click()

        # Then it succeeds
        # Wait until page refreshes to avoid causing a broken pipe error (#623)
        def update_password_success():
            assert "Password updated." in journ_app_nav.driver.page_source

        journ_app_nav.nav_helper.wait_for(update_password_success)

        # And the second journalist is able to login using the new password
        journ_app_nav.journalist_logs_out()
        journ_app_nav.journalist_logs_in(
            username=_SECOND_JOURNALIST_USERNAME,
            password=new_password,
            otp_secret=_SECOND_JOURNALIST_OTP_SECRET,
        )
        assert journ_app_nav.is_on_journalist_homepage()

    def test_admin_edits_hotp_secret(
        self, sd_servers_v2_with_second_journalist, firefox_web_driver
    ):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        # And they went to the "edit user" page for the second journalist
        journ_app_nav = self._admin_logs_in_and_goes_to_edit_page_for_second_journalist(
            sd_servers_result=sd_servers_v2_with_second_journalist,
            firefox_web_driver=firefox_web_driver,
        )

        # When the admin resets the second journalist's hotp
        def _admin_visits_reset_2fa_hotp_step() -> None:
            # 2FA reset buttons show a tooltip with explanatory text on hover.
            # Also, confirm the text on the tooltip is the correct one.
            hotp_reset_button = journ_app_nav.driver.find_elements_by_id("reset-two-factor-hotp")[0]
            hotp_reset_button.location_once_scrolled_into_view
            ActionChains(journ_app_nav.driver).move_to_element(hotp_reset_button).perform()

            time.sleep(1)

            tip_opacity = journ_app_nav.driver.find_elements_by_css_selector(
                "#button-reset-two-factor-hotp span.tooltip"
            )[0].value_of_css_property("opacity")
            tip_text = journ_app_nav.driver.find_elements_by_css_selector(
                "#button-reset-two-factor-hotp span.tooltip"
            )[0].text
            assert tip_opacity == "1"

            if not journ_app_nav.accept_languages:
                assert (
                    tip_text == "Reset two-factor authentication for security keys, like a YubiKey"
                )

            journ_app_nav.nav_helper.safe_click_by_id("button-reset-two-factor-hotp")

        # Run the above step in a retry loop
        self._retry_2fa_pop_ups(
            journ_app_nav, _admin_visits_reset_2fa_hotp_step, "reset-two-factor-hotp"
        )

        # Then it succeeds
        journ_app_nav.nav_helper.wait_for(
            lambda: journ_app_nav.driver.find_element_by_css_selector('input[name="otp_secret"]')
        )

    @staticmethod
    def _retry_2fa_pop_ups(
        journ_app_nav: JournalistAppNavigator, navigation_step: Callable, button_to_click: str
    ) -> None:
        """Clicking on Selenium alerts can be flaky. We need to retry them if they timeout."""
        for i in range(15):
            try:
                try:
                    # This is the button we click to trigger the alert.
                    journ_app_nav.nav_helper.wait_for(
                        lambda: journ_app_nav.driver.find_elements_by_id(button_to_click)[0]
                    )
                except IndexError:
                    # If the button isn't there, then the alert is up from the last
                    # time we attempted to run this test. Switch to it and accept it.
                    journ_app_nav.nav_helper.alert_wait()
                    journ_app_nav.nav_helper.alert_accept()
                    break

                # The alert isn't up. Run the rest of the logic.
                navigation_step()

                journ_app_nav.nav_helper.alert_wait()
                journ_app_nav.nav_helper.alert_accept()
                break
            except TimeoutException:
                # Selenium has failed to click, and the confirmation
                # alert didn't happen. We'll try again.
                logging.info("Selenium has failed to click; retrying.")

    def test_admin_edits_totp_secret(
        self, sd_servers_v2_with_second_journalist, firefox_web_driver
    ):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        # And they went to the "edit user" page for the second journalist
        journ_app_nav = self._admin_logs_in_and_goes_to_edit_page_for_second_journalist(
            sd_servers_result=sd_servers_v2_with_second_journalist,
            firefox_web_driver=firefox_web_driver,
        )

        # When the admin resets the second journalist's totp
        def _admin_visits_reset_2fa_totp_step():
            totp_reset_button = journ_app_nav.driver.find_elements_by_id("reset-two-factor-totp")[0]
            assert "/admin/reset-2fa-totp" in totp_reset_button.get_attribute("action")
            # 2FA reset buttons show a tooltip with explanatory text on hover.
            # Also, confirm the text on the tooltip is the correct one.
            totp_reset_button = journ_app_nav.driver.find_elements_by_css_selector(
                "#button-reset-two-factor-totp"
            )[0]
            totp_reset_button.location_once_scrolled_into_view
            ActionChains(journ_app_nav.driver).move_to_element(totp_reset_button).perform()

            time.sleep(1)

            tip_opacity = journ_app_nav.driver.find_elements_by_css_selector(
                "#button-reset-two-factor-totp span.tooltip"
            )[0].value_of_css_property("opacity")
            tip_text = journ_app_nav.driver.find_elements_by_css_selector(
                "#button-reset-two-factor-totp span.tooltip"
            )[0].text

            assert tip_opacity == "1"
            if not journ_app_nav.accept_languages:
                expected_text = "Reset two-factor authentication for mobile apps, such as FreeOTP"
                assert tip_text == expected_text

            journ_app_nav.nav_helper.safe_click_by_id("button-reset-two-factor-totp")

        # Run the above step in a retry loop
        self._retry_2fa_pop_ups(
            journ_app_nav, _admin_visits_reset_2fa_totp_step, "reset-two-factor-totp"
        )

        # Then it succeeds

    def test_admin_deletes_user(self, sd_servers_v2_with_second_journalist, firefox_web_driver):
        # Given an SD server with a second journalist created
        # And the first journalist logged into the journalist interface as an admin
        journ_app_nav = JournalistAppNavigator(
            journalist_app_base_url=sd_servers_v2_with_second_journalist.journalist_app_base_url,
            web_driver=firefox_web_driver,
        )
        assert sd_servers_v2_with_second_journalist.journalist_is_admin
        journ_app_nav.journalist_logs_in(
            username=sd_servers_v2_with_second_journalist.journalist_username,
            password=sd_servers_v2_with_second_journalist.journalist_password,
            otp_secret=sd_servers_v2_with_second_journalist.journalist_otp_secret,
        )

        # When the admin deletes the second journalist
        journ_app_nav.admin_visits_admin_interface()
        for i in range(15):
            try:
                journ_app_nav.nav_helper.safe_click_by_css_selector(".delete-user a")
                journ_app_nav.nav_helper.wait_for(
                    lambda: expected_conditions.element_to_be_clickable((By.ID, "delete-selected"))
                )
                journ_app_nav.nav_helper.safe_click_by_id("delete-selected")
                journ_app_nav.nav_helper.alert_wait()
                journ_app_nav.nav_helper.alert_accept()
                break
            except TimeoutException:
                # Selenium has failed to click, and the confirmation
                # alert didn't happen. Try once more.
                logging.info("Selenium has failed to click yet again; retrying.")

        # Then it succeeds
        def user_deleted():
            flash_msg = journ_app_nav.driver.find_element_by_css_selector(".flash")
            assert "Deleted user" in flash_msg.text

        journ_app_nav.nav_helper.wait_for(user_deleted)


# TODO(AD): Will be refactored in my next PR
class TestAdminInterfaceEditConfig(
    ft.FunctionalTest,
    journalist_navigation_steps.JournalistNavigationStepsMixin,
    source_navigation_steps.SourceNavigationStepsMixin,
):
    def test_admin_updates_image(self):
        self._admin_logs_in()
        self._admin_visits_admin_interface()
        self._admin_visits_system_config_page()
        self._admin_updates_logo_image()

    def test_ossec_alert_button(self):
        self._admin_logs_in()
        self._admin_visits_admin_interface()
        self._admin_visits_system_config_page()
        self._admin_can_send_test_alert()

    def test_disallow_file_submission(self):
        self._admin_logs_in()
        self._admin_visits_admin_interface()
        self._admin_visits_system_config_page()
        self._admin_disallows_document_uploads()

        self._source_visits_source_homepage()
        self._source_chooses_to_submit_documents()
        self._source_continues_to_submit_page(files_allowed=False)
        self._source_does_not_sees_document_attachment_item()

    def test_allow_file_submission(self):
        self._admin_logs_in()
        self._admin_visits_admin_interface()
        self._admin_visits_system_config_page()
        self._admin_disallows_document_uploads()
        self._admin_allows_document_uploads()

        self._source_visits_source_homepage()
        self._source_chooses_to_submit_documents()
        self._source_continues_to_submit_page()
        self._source_sees_document_attachment_item()

    def test_orgname_is_changed(self):
        self._admin_logs_in()
        self._admin_visits_admin_interface()
        self._admin_visits_system_config_page()
        self._admin_sets_organization_name()

        self._source_visits_source_homepage()
        self._source_sees_orgname(name=self.orgname_new)
        self._source_chooses_to_submit_documents()
        self._source_continues_to_submit_page()
        self._source_sees_orgname(name=self.orgname_new)
