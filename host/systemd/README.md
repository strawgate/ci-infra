# Bare-metal Docker maintenance

`docker-weekly-prune.timer` runs Sunday at 03:00 in `docker-host`'s local
timezone. The oneshot service caps BuildKit cache at 150 GB and removes
images unused by containers for 168 hours. It does **not** prune containers
or volumes, restart Docker, or touch the ARC VM's separate k3s containerd.

The service and timer are installed under `/etc/systemd/system` on
`docker-host`. After changing them, copy both files to the host, run
`sudo systemd-analyze verify` on the copies, then use `sudo install -m 0644`
to replace the installed units. Finish with `sudo systemctl daemon-reload`,
`sudo systemctl enable --now docker-weekly-prune.timer`, and
`systemctl list-timers docker-weekly-prune.timer` to verify the next run.
Do not start the service manually unless an immediate prune is intended.
