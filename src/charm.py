#!/usr/bin/env python3
# Copyright 2025 Marcus Boden (marcus.boden@canonical.com)
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging
import pathlib

from pydantic import BaseModel

import ops

from pathlib import Path

from charms.operator_libs_linux.v2 import snap
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)

RESOURCE_NAME = "exporter-snap"
RULES_DIR = "/etc/generic-exporter-rules/"

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]

class SnapNameNotConfigured(Exception):
    pass

class ExporterConfig(BaseModel):
    exporter_port: int
    snap_name: str | None = None
    classic: bool
    metrics_path: str
    alert_rules: str | None = None

class GenericExporterCharm(ops.CharmBase):
    """Install and configure any prometheus exporter snap."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        try:
            self._config = self.load_config(ExporterConfig)
        except ValueError as e:
            logger.error(f'Configuration error: {e}')
            self.unit.status = ops.BlockedStatus(str(e))
            return

        self.framework.observe(self.on.install, self._install_snap)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._install_snap)

        # COS integration
        self.cos = COSAgentProvider(
            self,
            metrics_endpoints=[{
                "path": f'/{self._config.metrics_path}',
                "port": self._config.exporter_port
            }],
            metrics_rules_dir=RULES_DIR,
            refresh_events=[self.on.config_changed],
        )

    def _install_from_resource(self, resource_path: Path):
        logger.info("Installing snap from resource %s", resource_path)
        snap.install_local(filename=str(resource_path), dangerous=True, classic=self._config.classic)

    def _install_from_store(self, name):
        cache = snap.SnapCache()
        logger.info(f"Installing snap {name} from store")
        installed = cache[name]
        if not installed.present:
            installed.ensure(snap.SnapState.Latest, classic=self._config.classic)

    def _install_snap(self, event):
        """Install snap from resource or store."""
        try:
            path = self.model.resources.fetch(RESOURCE_NAME)
            self._install_from_resource(path)
            self.unit.status = ops.ActiveStatus("snap installed")
            return
        except ops.model.ModelError:
            logger.info("No resource configured, will use snapstore")

        cfg_name = self._config.snap_name
        if not cfg_name or cfg_name == "None":
            err = "Either snap-name needs to be configured or a snap needs to be attached as a resource"
            logger.error(err)
            self.unit.status = ops.BlockedStatus(err)
            raise SnapNameNotConfigured(err)

        self._install_from_store(cfg_name)
        self.unit.status = ops.ActiveStatus("snap installed")

    def _configure(self, _):
        """Apply snap configuration and alert rules."""

        # write alert rules
        rules_dir = Path(RULES_DIR)
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules = self._config.alert_rules
        (rules_dir / "alerts.rules").write_text(rules or "# no alerts\n")

        self.unit.status = ops.ActiveStatus("configured")


if __name__ == "__main__":
    ops.main(GenericExporterCharm)