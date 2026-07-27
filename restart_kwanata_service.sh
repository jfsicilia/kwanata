#!/bin/bash
cp *.py ~/.local/lib/kwanata/
systemctl --user restart kwanata.service
journalctl --user -u kwanata.service -f
