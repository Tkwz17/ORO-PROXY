#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt/oroproxy"
cp -a "$(dirname "$0")/files/." "${ROOTFS_DIR}/opt/oroproxy/"

on_chroot << 'INNER'
chmod +x /opt/oroproxy/scripts/*.sh
chmod +x /opt/oroproxy/services/ap-manager/manage_auth_set.sh
install -m 0644 /opt/oroproxy/systemd/*.service /etc/systemd/system/
install -m 0644 /opt/oroproxy/systemd/*.timer /etc/systemd/system/
systemctl enable oroproxy-first-boot.service
systemctl enable oroproxy-update-check.timer
INNER
