"""Tests for constants and PACKAGE_SERVICES."""

from __future__ import annotations

from pistomp_recovery.constants import (
    DOMAIN_FACETS,
    FACET_NAMES,
    PACKAGE_SERVICES,
    PISTOMP_SERVICES,
    services_for_packages,
)


class TestPackageServices:
    def test_known_package_returns_mapped_services(self) -> None:
        result: list[str] = services_for_packages(["jack2-pistomp"])
        assert result == ["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"]

    def test_pi_stomp_returns_its_service(self) -> None:
        result: list[str] = services_for_packages(["pi-stomp"])
        assert result == ["mod-ala-pi-stomp"]

    def test_unknown_package_returns_full_chain(self) -> None:
        result: list[str] = services_for_packages(["some-unknown-pkg"])
        assert result == list(PISTOMP_SERVICES)

    def test_multiple_packages_ordered(self) -> None:
        result: list[str] = services_for_packages(
            ["mod-host-pistomp", "pi-stomp"]
        )
        assert result == ["mod-host", "mod-ui", "mod-ala-pi-stomp"]

    def test_empty_list_returns_empty(self) -> None:
        result: list[str] = services_for_packages([])
        assert result == []

    def test_pistomp_recovery_returns_empty(self) -> None:
        result: list[str] = services_for_packages(["pistomp-recovery"])
        assert result == []

    def test_all_pistomp_packages_have_entries(self) -> None:
        from pistomp_recovery.constants import PISTOMP_PACKAGES
        for pkg in PISTOMP_PACKAGES:
            assert pkg in PACKAGE_SERVICES


class TestDomainFacets:
    def test_every_facet_in_map_is_registered(self) -> None:
        """Every facet name in DOMAIN_FACETS must appear in FACET_NAMES."""
        all_mapped: set[str] = {f for facets in DOMAIN_FACETS.values() for f in facets}
        assert all_mapped <= set(FACET_NAMES), (
            f"DOMAIN_FACETS references unknown facets: {all_mapped - set(FACET_NAMES)}"
        )

    def test_every_registered_facet_is_reachable(self) -> None:
        """Every facet in FACET_NAMES must be reachable from exactly one domain.

        This catches the original bug where the packages facet was registered
        but never wired to a domain, making it invisible to the UI.
        """
        all_mapped: set[str] = {f for facets in DOMAIN_FACETS.values() for f in facets}
        orphans = set(FACET_NAMES) - all_mapped
        assert not orphans, f"Facets registered but reachable from no domain: {orphans}"

    def test_no_facet_appears_in_multiple_domains(self) -> None:
        seen: set[str] = set()
        for domain, facets in DOMAIN_FACETS.items():
            for f in facets:
                assert f not in seen, (
                    f"Facet {f!r} appears in multiple domains (second: {domain!r})"
                )
                seen.add(f)

    def test_all_domains_have_at_least_one_facet(self) -> None:
        for domain, facets in DOMAIN_FACETS.items():
            assert facets, f"Domain {domain!r} has no facets"
