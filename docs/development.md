# Utvikling av Agentbox

Kjør fra en arbeidskopi av repoet. Python 3.12 eller nyere og uv kreves.
Arbeid på egne grener og oppdater dokumentasjon før squash merge til `main`;
se [bidragsreglene](../AGENTS.md).

## Lokale kontroller

```sh
uv sync --extra dev --locked
uv run --locked pytest
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
bash -n scripts/install.sh scripts/lab/*.sh src/agentbox/completions/agentbox.bash
```

`pytest` kjører enhetstester som standard. Integrasjonstesten krever installert
kontrollverktøy, `AGENTBOX_LAB=1` og vertsnavnet `agentbox-lab`.

## Disponibel integrasjonslab

Den disponible KVM-laben krever QEMU, `qemu-img`, `xorriso`, curl og SSH.
Labkommandoene nedenfor skal kjøres utenfor en agentsandkasse som sperrer KVM:

```sh
scripts/lab/vm.sh prepare
scripts/lab/vm.sh start
scripts/lab/vm.sh ssh
scripts/lab/vm.sh stop
```

Bootstrap- og nettverksprøver har en eksplisitt `agentbox-lab`-vertskontroll.
Reproduksjon av testløpet er beskrevet i [teststatus](test-results.md).
Koden kopieres inn med tar/SSH; vertens mapper deles ikke inn i VM-en.

