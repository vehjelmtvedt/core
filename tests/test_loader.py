"""Test to verify that we can load components."""
import asyncio
from unittest.mock import patch

import pytest

from homeassistant import loader
from homeassistant.components import http, hue
from homeassistant.components.hue import light as hue_light
from homeassistant.core import HomeAssistant, callback

from .common import MockModule, async_get_persistent_notifications, mock_integration


async def test_circular_component_dependencies(hass: HomeAssistant) -> None:
    """Test if we can detect circular dependencies of components."""
    mock_integration(hass, MockModule("mod1"))
    mock_integration(hass, MockModule("mod2", ["mod1"]))
    mock_integration(hass, MockModule("mod3", ["mod1"]))
    mod_4 = mock_integration(hass, MockModule("mod4", ["mod2", "mod3"]))

    deps = await loader._async_component_dependencies(hass, mod_4)
    assert deps == {"mod1", "mod2", "mod3", "mod4"}

    # Create a circular dependency
    mock_integration(hass, MockModule("mod1", ["mod4"]))
    with pytest.raises(loader.CircularDependency):
        await loader._async_component_dependencies(hass, mod_4)

    # Create a different circular dependency
    mock_integration(hass, MockModule("mod1", ["mod3"]))
    with pytest.raises(loader.CircularDependency):
        await loader._async_component_dependencies(hass, mod_4)

    # Create a circular after_dependency
    mock_integration(
        hass, MockModule("mod1", partial_manifest={"after_dependencies": ["mod4"]})
    )
    with pytest.raises(loader.CircularDependency):
        await loader._async_component_dependencies(hass, mod_4)

    # Create a different circular after_dependency
    mock_integration(
        hass, MockModule("mod1", partial_manifest={"after_dependencies": ["mod3"]})
    )
    with pytest.raises(loader.CircularDependency):
        await loader._async_component_dependencies(hass, mod_4)


async def test_nonexistent_component_dependencies(hass: HomeAssistant) -> None:
    """Test if we can detect nonexistent dependencies of components."""
    mod_1 = mock_integration(hass, MockModule("mod1", ["nonexistent"]))
    with pytest.raises(loader.IntegrationNotFound):
        await loader._async_component_dependencies(hass, mod_1)


def test_component_loader(hass: HomeAssistant) -> None:
    """Test loading components."""
    components = loader.Components(hass)
    assert components.http.CONFIG_SCHEMA is http.CONFIG_SCHEMA
    assert hass.components.http.CONFIG_SCHEMA is http.CONFIG_SCHEMA


def test_component_loader_non_existing(hass: HomeAssistant) -> None:
    """Test loading components."""
    components = loader.Components(hass)
    with pytest.raises(ImportError):
        components.non_existing


async def test_component_wrapper(hass: HomeAssistant) -> None:
    """Test component wrapper."""
    components = loader.Components(hass)
    components.persistent_notification.async_create("message")

    notifications = async_get_persistent_notifications(hass)
    assert len(notifications)


async def test_helpers_wrapper(hass: HomeAssistant) -> None:
    """Test helpers wrapper."""
    helpers = loader.Helpers(hass)

    result = []

    @callback
    def discovery_callback(service, discovered):
        """Handle discovery callback."""
        result.append(discovered)

    helpers.discovery.async_listen("service_name", discovery_callback)

    await helpers.discovery.async_discover("service_name", "hello", None, {})
    await hass.async_block_till_done()

    assert result == ["hello"]


async def test_custom_component_name(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Test the name attribute of custom components."""
    with pytest.raises(loader.IntegrationNotFound):
        await loader.async_get_integration(hass, "test_standalone")

    integration = await loader.async_get_integration(hass, "test_package")

    int_comp = integration.get_component()
    assert int_comp.__name__ == "custom_components.test_package"
    assert int_comp.__package__ == "custom_components.test_package"

    comp = hass.components.test_package
    assert comp.__name__ == "custom_components.test_package"
    assert comp.__package__ == "custom_components.test_package"

    integration = await loader.async_get_integration(hass, "test")
    platform = integration.get_platform("light")
    assert platform.__name__ == "custom_components.test.light"
    assert platform.__package__ == "custom_components.test"

    # Test custom components is mounted
    from custom_components.test_package import TEST

    assert TEST == 5


async def test_log_warning_custom_component(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    enable_custom_integrations: None,
) -> None:
    """Test that we log a warning when loading a custom component."""

    await loader.async_get_integration(hass, "test_package")
    assert "We found a custom integration test_package" in caplog.text

    await loader.async_get_integration(hass, "test")
    assert "We found a custom integration test " in caplog.text


async def test_custom_integration_version_not_valid(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    enable_custom_integrations: None,
) -> None:
    """Test that we log a warning when custom integrations have a invalid version."""
    with pytest.raises(loader.IntegrationNotFound):
        await loader.async_get_integration(hass, "test_no_version")

    assert (
        "The custom integration 'test_no_version' does not have a version key in the"
        " manifest file and was blocked from loading."
    ) in caplog.text

    with pytest.raises(loader.IntegrationNotFound):
        await loader.async_get_integration(hass, "test2")
    assert (
        "The custom integration 'test_bad_version' does not have a valid version key"
        " (bad) in the manifest file and was blocked from loading."
    ) in caplog.text


async def test_get_integration(hass: HomeAssistant) -> None:
    """Test resolving integration."""
    with pytest.raises(loader.IntegrationNotLoaded):
        loader.async_get_loaded_integration(hass, "hue")

    integration = await loader.async_get_integration(hass, "hue")
    assert hue == integration.get_component()
    assert hue_light == integration.get_platform("light")

    integration = loader.async_get_loaded_integration(hass, "hue")
    assert hue == integration.get_component()
    assert hue_light == integration.get_platform("light")


async def test_async_get_component(hass: HomeAssistant) -> None:
    """Test resolving integration."""
    with pytest.raises(loader.IntegrationNotLoaded):
        loader.async_get_loaded_integration(hass, "hue")

    integration = await loader.async_get_integration(hass, "hue")
    assert await integration.async_get_component() == hue
    assert integration.get_platform("light") == hue_light

    integration = loader.async_get_loaded_integration(hass, "hue")
    assert await integration.async_get_component() == hue
    assert integration.get_platform("light") == hue_light


async def test_get_integration_exceptions(hass: HomeAssistant) -> None:
    """Test resolving integration."""
    integration = await loader.async_get_integration(hass, "hue")

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ValueError("Boom")
    ):
        assert hue == integration.get_component()

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ValueError("Boom")
    ):
        assert hue_light == integration.get_platform("light")


async def test_get_platform_caches_failures_when_component_loaded(
    hass: HomeAssistant,
) -> None:
    """Test get_platform cache failures only when the component is loaded."""
    integration = await loader.async_get_integration(hass, "hue")

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert integration.get_component() == hue

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert integration.get_platform("light") == hue_light

    # Hue is not loaded so we should still hit the import_module path
    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert integration.get_platform("light") == hue_light

    assert integration.get_component() == hue

    # Hue is loaded so we should cache the import_module failure now
    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert integration.get_platform("light") == hue_light

    # Hue is loaded and the last call should have cached the import_module failure
    with pytest.raises(ImportError):
        assert integration.get_platform("light") == hue_light


async def test_async_get_platform_caches_failures_when_component_loaded(
    hass: HomeAssistant,
) -> None:
    """Test async_get_platform cache failures only when the component is loaded."""
    integration = await loader.async_get_integration(hass, "hue")

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert integration.get_component() == hue

    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert await integration.async_get_platform("light") == hue_light

    # Hue is not loaded so we should still hit the import_module path
    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert await integration.async_get_platform("light") == hue_light

    assert integration.get_component() == hue

    # Hue is loaded so we should cache the import_module failure now
    with pytest.raises(ImportError), patch(
        "homeassistant.loader.importlib.import_module", side_effect=ImportError("Boom")
    ):
        assert await integration.async_get_platform("light") == hue_light

    # Hue is loaded and the last call should have cached the import_module failure
    with pytest.raises(ImportError):
        assert await integration.async_get_platform("light") == hue_light


async def test_get_integration_legacy(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Test resolving integration."""
    integration = await loader.async_get_integration(hass, "test_embedded")
    assert integration.get_component().DOMAIN == "test_embedded"
    assert integration.get_platform("switch") is not None


async def test_get_integration_custom_component(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Test resolving integration."""
    integration = await loader.async_get_integration(hass, "test_package")
    assert integration.get_component().DOMAIN == "test_package"
    assert integration.name == "Test Package"


def test_integration_properties(hass: HomeAssistant) -> None:
    """Test integration properties."""
    integration = loader.Integration(
        hass,
        "homeassistant.components.hue",
        None,
        {
            "name": "Philips Hue",
            "domain": "hue",
            "dependencies": ["test-dep"],
            "requirements": ["test-req==1.0.0"],
            "zeroconf": ["_hue._tcp.local."],
            "homekit": {"models": ["BSB002"]},
            "dhcp": [
                {"hostname": "tesla_*", "macaddress": "4CFCAA*"},
                {"hostname": "tesla_*", "macaddress": "044EAF*"},
                {"hostname": "tesla_*", "macaddress": "98ED5C*"},
                {"registered_devices": True},
            ],
            "bluetooth": [{"manufacturer_id": 76, "manufacturer_data_start": [0x06]}],
            "usb": [
                {"vid": "10C4", "pid": "EA60"},
                {"vid": "1CF1", "pid": "0030"},
                {"vid": "1A86", "pid": "7523"},
                {"vid": "10C4", "pid": "8A2A"},
            ],
            "ssdp": [
                {
                    "manufacturer": "Royal Philips Electronics",
                    "modelName": "Philips hue bridge 2012",
                },
                {
                    "manufacturer": "Royal Philips Electronics",
                    "modelName": "Philips hue bridge 2015",
                },
                {"manufacturer": "Signify", "modelName": "Philips hue bridge 2015"},
            ],
            "mqtt": ["hue/discovery"],
            "version": "1.0.0",
        },
    )
    assert integration.name == "Philips Hue"
    assert integration.domain == "hue"
    assert integration.homekit == {"models": ["BSB002"]}
    assert integration.zeroconf == ["_hue._tcp.local."]
    assert integration.dhcp == [
        {"hostname": "tesla_*", "macaddress": "4CFCAA*"},
        {"hostname": "tesla_*", "macaddress": "044EAF*"},
        {"hostname": "tesla_*", "macaddress": "98ED5C*"},
        {"registered_devices": True},
    ]
    assert integration.usb == [
        {"vid": "10C4", "pid": "EA60"},
        {"vid": "1CF1", "pid": "0030"},
        {"vid": "1A86", "pid": "7523"},
        {"vid": "10C4", "pid": "8A2A"},
    ]
    assert integration.bluetooth == [
        {"manufacturer_id": 76, "manufacturer_data_start": [0x06]}
    ]
    assert integration.ssdp == [
        {
            "manufacturer": "Royal Philips Electronics",
            "modelName": "Philips hue bridge 2012",
        },
        {
            "manufacturer": "Royal Philips Electronics",
            "modelName": "Philips hue bridge 2015",
        },
        {"manufacturer": "Signify", "modelName": "Philips hue bridge 2015"},
    ]
    assert integration.mqtt == ["hue/discovery"]
    assert integration.dependencies == ["test-dep"]
    assert integration.requirements == ["test-req==1.0.0"]
    assert integration.is_built_in is True
    assert integration.version == "1.0.0"

    integration = loader.Integration(
        hass,
        "custom_components.hue",
        None,
        {
            "name": "Philips Hue",
            "domain": "hue",
            "dependencies": ["test-dep"],
            "requirements": ["test-req==1.0.0"],
        },
    )
    assert integration.is_built_in is False
    assert integration.homekit is None
    assert integration.zeroconf is None
    assert integration.dhcp is None
    assert integration.bluetooth is None
    assert integration.usb is None
    assert integration.ssdp is None
    assert integration.mqtt is None
    assert integration.version is None

    integration = loader.Integration(
        hass,
        "custom_components.hue",
        None,
        {
            "name": "Philips Hue",
            "domain": "hue",
            "dependencies": ["test-dep"],
            "zeroconf": [{"type": "_hue._tcp.local.", "name": "hue*"}],
            "requirements": ["test-req==1.0.0"],
        },
    )
    assert integration.is_built_in is False
    assert integration.homekit is None
    assert integration.zeroconf == [{"type": "_hue._tcp.local.", "name": "hue*"}]
    assert integration.dhcp is None
    assert integration.usb is None
    assert integration.bluetooth is None
    assert integration.ssdp is None


async def test_integrations_only_once(hass: HomeAssistant) -> None:
    """Test that we load integrations only once."""
    int_1 = hass.async_create_task(loader.async_get_integration(hass, "hue"))
    int_2 = hass.async_create_task(loader.async_get_integration(hass, "hue"))

    assert await int_1 is await int_2


def _get_test_integration(
    hass: HomeAssistant, name: str, config_flow: bool, import_executor: bool = False
) -> loader.Integration:
    """Return a generated test integration."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "dependencies": [],
            "requirements": [],
            "zeroconf": [f"_{name}._tcp.local."],
            "homekit": {"models": [name]},
            "ssdp": [{"manufacturer": name, "modelName": name}],
            "mqtt": [f"{name}/discovery"],
            "import_executor": import_executor,
        },
    )


def _get_test_integration_with_application_credentials(hass, name):
    """Return a generated test integration with application_credentials support."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": True,
            "dependencies": ["application_credentials"],
            "requirements": [],
            "zeroconf": [f"_{name}._tcp.local."],
            "homekit": {"models": [name]},
            "ssdp": [{"manufacturer": name, "modelName": name}],
            "mqtt": [f"{name}/discovery"],
        },
    )


def _get_test_integration_with_zeroconf_matcher(hass, name, config_flow):
    """Return a generated test integration with a zeroconf matcher."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "dependencies": [],
            "requirements": [],
            "zeroconf": [{"type": f"_{name}._tcp.local.", "name": f"{name}*"}],
            "homekit": {"models": [name]},
            "ssdp": [{"manufacturer": name, "modelName": name}],
        },
    )


def _get_test_integration_with_legacy_zeroconf_matcher(hass, name, config_flow):
    """Return a generated test integration with a legacy zeroconf matcher."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "dependencies": [],
            "requirements": [],
            "zeroconf": [
                {
                    "type": f"_{name}._tcp.local.",
                    "macaddress": "AABBCC*",
                    "manufacturer": "legacy*",
                    "model": "legacy*",
                    "name": f"{name}*",
                }
            ],
            "homekit": {"models": [name]},
            "ssdp": [{"manufacturer": name, "modelName": name}],
        },
    )


def _get_test_integration_with_dhcp_matcher(hass, name, config_flow):
    """Return a generated test integration with a dhcp matcher."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "dependencies": [],
            "requirements": [],
            "zeroconf": [],
            "dhcp": [
                {"hostname": "tesla_*", "macaddress": "4CFCAA*"},
                {"hostname": "tesla_*", "macaddress": "044EAF*"},
                {"hostname": "tesla_*", "macaddress": "98ED5C*"},
            ],
            "homekit": {"models": [name]},
            "ssdp": [{"manufacturer": name, "modelName": name}],
        },
    )


def _get_test_integration_with_bluetooth_matcher(hass, name, config_flow):
    """Return a generated test integration with a bluetooth matcher."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "bluetooth": [
                {
                    "local_name": "Prodigio_*",
                },
            ],
        },
    )


def _get_test_integration_with_usb_matcher(hass, name, config_flow):
    """Return a generated test integration with a usb matcher."""
    return loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": config_flow,
            "dependencies": [],
            "requirements": [],
            "usb": [
                {
                    "vid": "10C4",
                    "pid": "EA60",
                    "known_devices": ["slae.sh cc2652rb stick"],
                },
                {"vid": "1CF1", "pid": "0030", "known_devices": ["Conbee II"]},
                {
                    "vid": "1A86",
                    "pid": "7523",
                    "known_devices": ["Electrolama zig-a-zig-ah"],
                },
                {"vid": "10C4", "pid": "8A2A", "known_devices": ["Nortek HUSBZB-1"]},
            ],
        },
    )


async def test_get_custom_components(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Verify that custom components are cached."""
    test_1_integration = _get_test_integration(hass, "test_1", False)
    test_2_integration = _get_test_integration(hass, "test_2", True)

    name = "homeassistant.loader._async_get_custom_components"
    with patch(name) as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        integrations = await loader.async_get_custom_components(hass)
        assert integrations == mock_get.return_value
        integrations = await loader.async_get_custom_components(hass)
        assert integrations == mock_get.return_value
        mock_get.assert_called_once_with(hass)


async def test_get_config_flows(hass: HomeAssistant) -> None:
    """Verify that custom components with config_flow are available."""
    test_1_integration = _get_test_integration(hass, "test_1", False)
    test_2_integration = _get_test_integration(hass, "test_2", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        flows = await loader.async_get_config_flows(hass)
        assert "test_2" in flows
        assert "test_1" not in flows


async def test_get_zeroconf(hass: HomeAssistant) -> None:
    """Verify that custom components with zeroconf are found."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration_with_zeroconf_matcher(
        hass, "test_2", True
    )

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        zeroconf = await loader.async_get_zeroconf(hass)
        assert zeroconf["_test_1._tcp.local."] == [{"domain": "test_1"}]
        assert zeroconf["_test_2._tcp.local."] == [
            {"domain": "test_2", "name": "test_2*"}
        ]


async def test_get_application_credentials(hass: HomeAssistant) -> None:
    """Verify that custom components with application_credentials are found."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration_with_application_credentials(
        hass, "test_2"
    )

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        application_credentials = await loader.async_get_application_credentials(hass)
        assert "test_2" in application_credentials
        assert "test_1" not in application_credentials


async def test_get_zeroconf_back_compat(hass: HomeAssistant) -> None:
    """Verify that custom components with zeroconf are found and legacy matchers are converted."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration_with_legacy_zeroconf_matcher(
        hass, "test_2", True
    )

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        zeroconf = await loader.async_get_zeroconf(hass)
        assert zeroconf["_test_1._tcp.local."] == [{"domain": "test_1"}]
        assert zeroconf["_test_2._tcp.local."] == [
            {
                "domain": "test_2",
                "name": "test_2*",
                "properties": {
                    "macaddress": "aabbcc*",
                    "model": "legacy*",
                    "manufacturer": "legacy*",
                },
            }
        ]


async def test_get_bluetooth(hass: HomeAssistant) -> None:
    """Verify that custom components with bluetooth are found."""
    test_1_integration = _get_test_integration_with_bluetooth_matcher(
        hass, "test_1", True
    )
    test_2_integration = _get_test_integration_with_dhcp_matcher(hass, "test_2", True)
    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        bluetooth = await loader.async_get_bluetooth(hass)
        bluetooth_for_domain = [
            entry for entry in bluetooth if entry["domain"] == "test_1"
        ]
        assert bluetooth_for_domain == [
            {"domain": "test_1", "local_name": "Prodigio_*"},
        ]


async def test_get_dhcp(hass: HomeAssistant) -> None:
    """Verify that custom components with dhcp are found."""
    test_1_integration = _get_test_integration_with_dhcp_matcher(hass, "test_1", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
        }
        dhcp = await loader.async_get_dhcp(hass)
        dhcp_for_domain = [entry for entry in dhcp if entry["domain"] == "test_1"]
        assert dhcp_for_domain == [
            {"domain": "test_1", "hostname": "tesla_*", "macaddress": "4CFCAA*"},
            {"domain": "test_1", "hostname": "tesla_*", "macaddress": "044EAF*"},
            {"domain": "test_1", "hostname": "tesla_*", "macaddress": "98ED5C*"},
        ]


async def test_get_usb(hass: HomeAssistant) -> None:
    """Verify that custom components with usb matchers are found."""
    test_1_integration = _get_test_integration_with_usb_matcher(hass, "test_1", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
        }
        usb = await loader.async_get_usb(hass)
        usb_for_domain = [entry for entry in usb if entry["domain"] == "test_1"]
        assert usb_for_domain == [
            {"domain": "test_1", "vid": "10C4", "pid": "EA60"},
            {"domain": "test_1", "vid": "1CF1", "pid": "0030"},
            {"domain": "test_1", "vid": "1A86", "pid": "7523"},
            {"domain": "test_1", "vid": "10C4", "pid": "8A2A"},
        ]


async def test_get_homekit(hass: HomeAssistant) -> None:
    """Verify that custom components with homekit are found."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration(hass, "test_2", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        homekit = await loader.async_get_homekit(hass)
        assert homekit["test_1"] == loader.HomeKitDiscoveredIntegration("test_1", True)
        assert homekit["test_2"] == loader.HomeKitDiscoveredIntegration("test_2", True)


async def test_get_ssdp(hass: HomeAssistant) -> None:
    """Verify that custom components with ssdp are found."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration(hass, "test_2", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        ssdp = await loader.async_get_ssdp(hass)
        assert ssdp["test_1"] == [{"manufacturer": "test_1", "modelName": "test_1"}]
        assert ssdp["test_2"] == [{"manufacturer": "test_2", "modelName": "test_2"}]


async def test_get_mqtt(hass: HomeAssistant) -> None:
    """Verify that custom components with MQTT are found."""
    test_1_integration = _get_test_integration(hass, "test_1", True)
    test_2_integration = _get_test_integration(hass, "test_2", True)

    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {
            "test_1": test_1_integration,
            "test_2": test_2_integration,
        }
        mqtt = await loader.async_get_mqtt(hass)
        assert mqtt["test_1"] == ["test_1/discovery"]
        assert mqtt["test_2"] == ["test_2/discovery"]


async def test_import_platform_executor(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Test import a platform in the executor."""
    integration = await loader.async_get_integration(
        hass, "test_package_loaded_executor"
    )

    config_flow_task_1 = asyncio.create_task(
        integration.async_get_platform("config_flow")
    )
    config_flow_task_2 = asyncio.create_task(
        integration.async_get_platform("config_flow")
    )
    config_flow_task_3 = asyncio.create_task(
        integration.async_get_platform("config_flow")
    )

    config_flow_task1_result = await config_flow_task_1
    config_flow_task2_result = await config_flow_task_2
    config_flow_task3_result = await config_flow_task_3

    assert (
        config_flow_task1_result == config_flow_task2_result == config_flow_task3_result
    )

    assert await config_flow_task1_result._async_has_devices(hass) is True


async def test_get_custom_components_recovery_mode(hass: HomeAssistant) -> None:
    """Test that we get empty custom components in recovery mode."""
    hass.config.recovery_mode = True
    assert await loader.async_get_custom_components(hass) == {}


async def test_custom_integration_missing_version(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test trying to load a custom integration without a version twice does not deadlock."""
    with pytest.raises(loader.IntegrationNotFound):
        await loader.async_get_integration(hass, "test_no_version")

    with pytest.raises(loader.IntegrationNotFound):
        await loader.async_get_integration(hass, "test_no_version")


async def test_custom_integration_missing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test trying to load a custom integration that is missing twice not deadlock."""
    with patch("homeassistant.loader.async_get_custom_components") as mock_get:
        mock_get.return_value = {}

        with pytest.raises(loader.IntegrationNotFound):
            await loader.async_get_integration(hass, "test1")

        with pytest.raises(loader.IntegrationNotFound):
            await loader.async_get_integration(hass, "test1")


async def test_validation(hass: HomeAssistant) -> None:
    """Test we raise if invalid domain passed in."""
    with pytest.raises(ValueError):
        await loader.async_get_integration(hass, "some.thing")


async def test_loggers(hass: HomeAssistant) -> None:
    """Test we can fetch the loggers from the integration."""
    name = "dummy"
    integration = loader.Integration(
        hass,
        f"homeassistant.components.{name}",
        None,
        {
            "name": name,
            "domain": name,
            "config_flow": True,
            "dependencies": [],
            "requirements": [],
            "loggers": ["name1", "name2"],
        },
    )
    assert integration.loggers == ["name1", "name2"]


CORE_ISSUE_TRACKER = (
    "https://github.com/home-assistant/core/issues?q=is%3Aopen+is%3Aissue"
)
CORE_ISSUE_TRACKER_BUILT_IN = (
    CORE_ISSUE_TRACKER + "+label%3A%22integration%3A+bla_built_in%22"
)
CORE_ISSUE_TRACKER_CUSTOM = (
    CORE_ISSUE_TRACKER + "+label%3A%22integration%3A+bla_custom%22"
)
CORE_ISSUE_TRACKER_CUSTOM_NO_TRACKER = (
    CORE_ISSUE_TRACKER + "+label%3A%22integration%3A+bla_custom_no_tracker%22"
)
CORE_ISSUE_TRACKER_HUE = CORE_ISSUE_TRACKER + "+label%3A%22integration%3A+hue%22"
CUSTOM_ISSUE_TRACKER = "https://blablabla.com"


@pytest.mark.parametrize(
    ("domain", "module", "issue_tracker"),
    [
        # If no information is available, open issue on core
        (None, None, CORE_ISSUE_TRACKER),
        ("hue", "homeassistant.components.hue.sensor", CORE_ISSUE_TRACKER_HUE),
        ("hue", None, CORE_ISSUE_TRACKER_HUE),
        ("bla_built_in", None, CORE_ISSUE_TRACKER_BUILT_IN),
        # Integration domain is not currently deduced from module
        (None, "homeassistant.components.hue.sensor", CORE_ISSUE_TRACKER),
        ("hue", "homeassistant.components.mqtt.sensor", CORE_ISSUE_TRACKER_HUE),
        # Custom integration with known issue tracker
        ("bla_custom", "custom_components.bla_custom.sensor", CUSTOM_ISSUE_TRACKER),
        ("bla_custom", None, CUSTOM_ISSUE_TRACKER),
        # Custom integration without known issue tracker
        (None, "custom_components.bla.sensor", None),
        ("bla_custom_no_tracker", "custom_components.bla_custom.sensor", None),
        ("bla_custom_no_tracker", None, None),
        ("hue", "custom_components.bla.sensor", None),
        # Integration domain has priority over module
        ("bla_custom_no_tracker", "homeassistant.components.bla_custom.sensor", None),
    ],
)
async def test_async_get_issue_tracker(
    hass, domain: str | None, module: str | None, issue_tracker: str | None
) -> None:
    """Test async_get_issue_tracker."""
    mock_integration(hass, MockModule("bla_built_in"))
    mock_integration(
        hass,
        MockModule(
            "bla_custom", partial_manifest={"issue_tracker": CUSTOM_ISSUE_TRACKER}
        ),
        built_in=False,
    )
    mock_integration(hass, MockModule("bla_custom_no_tracker"), built_in=False)
    assert (
        loader.async_get_issue_tracker(hass, integration_domain=domain, module=module)
        == issue_tracker
    )


@pytest.mark.parametrize(
    ("domain", "module", "issue_tracker"),
    [
        # If no information is available, open issue on core
        (None, None, CORE_ISSUE_TRACKER),
        ("hue", "homeassistant.components.hue.sensor", CORE_ISSUE_TRACKER_HUE),
        ("hue", None, CORE_ISSUE_TRACKER_HUE),
        ("bla_built_in", None, CORE_ISSUE_TRACKER_BUILT_IN),
        # Integration domain is not currently deduced from module
        (None, "homeassistant.components.hue.sensor", CORE_ISSUE_TRACKER),
        ("hue", "homeassistant.components.mqtt.sensor", CORE_ISSUE_TRACKER_HUE),
        # Custom integration with known issue tracker - can't find it without hass
        ("bla_custom", "custom_components.bla_custom.sensor", None),
        # Assumed to be a core integration without hass and without module
        ("bla_custom", None, CORE_ISSUE_TRACKER_CUSTOM),
    ],
)
async def test_async_get_issue_tracker_no_hass(
    hass, domain: str | None, module: str | None, issue_tracker: str
) -> None:
    """Test async_get_issue_tracker."""
    mock_integration(hass, MockModule("bla_built_in"))
    mock_integration(
        hass,
        MockModule(
            "bla_custom", partial_manifest={"issue_tracker": CUSTOM_ISSUE_TRACKER}
        ),
        built_in=False,
    )
    assert (
        loader.async_get_issue_tracker(None, integration_domain=domain, module=module)
        == issue_tracker
    )


REPORT_CUSTOM = (
    "report it to the author of the 'bla_custom_no_tracker' custom integration"
)
REPORT_CUSTOM_UNKNOWN = "report it to the custom integration author"


@pytest.mark.parametrize(
    ("domain", "module", "report_issue"),
    [
        (None, None, f"create a bug report at {CORE_ISSUE_TRACKER}"),
        ("bla_custom", None, f"create a bug report at {CUSTOM_ISSUE_TRACKER}"),
        ("bla_custom_no_tracker", None, REPORT_CUSTOM),
        (None, "custom_components.hue.sensor", REPORT_CUSTOM_UNKNOWN),
    ],
)
async def test_async_suggest_report_issue(
    hass, domain: str | None, module: str | None, report_issue: str
) -> None:
    """Test async_suggest_report_issue."""
    mock_integration(hass, MockModule("bla_built_in"))
    mock_integration(
        hass,
        MockModule(
            "bla_custom", partial_manifest={"issue_tracker": CUSTOM_ISSUE_TRACKER}
        ),
        built_in=False,
    )
    mock_integration(hass, MockModule("bla_custom_no_tracker"), built_in=False)
    assert (
        loader.async_suggest_report_issue(
            hass, integration_domain=domain, module=module
        )
        == report_issue
    )


async def test_config_folder_not_in_path(hass):
    """Test that config folder is not in path."""

    # Verify that we are unable to import this file from top level
    with pytest.raises(ImportError):
        import check_config_not_in_path  # noqa: F401

    # Verify that we are able to load the file with absolute path
    import tests.testing_config.check_config_not_in_path  # noqa: F401
