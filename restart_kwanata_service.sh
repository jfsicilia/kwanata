#!/bin/bash
cp kwanata.py ~/.local/lib/kwanata/
systemctl --user restart kwanata.service
journalctl --user -u kwanata.service -f
