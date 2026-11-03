# Delresearch: Bedrock-bearer-token

Status: dokumentasjon og lokal proxykode undersøkt 3. november 2026.
Brukeren bekreftet at dette gjelder AWS_BEARER_TOKEN_BEDROCK for Amazon
Bedrock. Ingen nye tester, modellkall eller kodeendringer er utført.
Øvrig research for CLI-/livssyklusendringene er ikke gjennomført.

## Grunnlag

- OpenAI Docs beskriver innebygde Codex-providere for Bedrock Runtime/Mantle,
  med AWS_BEARER_TOKEN_BEDROCK og eksplisitt region:
  https://learn.chatgpt.com/docs/amazon-bedrock
- Claude Code dokumenterer AWS_BEARER_TOKEN_BEDROCK og Bedrock-modus via
  CLAUDE_CODE_USE_BEDROCK. Nøkkelvariabelen velges foran AWS credential chain:
  https://code.claude.com/docs/en/amazon-bedrock
- OpenCode dokumenterer Bedrock-bearer-token med samme variabel og regionvalg:
  https://opencode.ai/docs/providers/#amazon-bedrock
- OpenCode dokumenterer proxyvariabler, NO_PROXY for loopback og
  NODE_EXTRA_CA_CERTS: https://opencode.ai/docs/network/
- Claude Code dokumenterer proxy/CA-oppsett:
  https://code.claude.com/docs/en/network-config
- AWS beskriver bearer-autentisering på Bedrocks Responses-endepunkt:
  https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html

## Lokal mekanisme

config.py tillater AWS_BEARER_TOKEN_BEDROCK som credential-klientnavn.
policy/control oppretter plassholder i agenten og gir bare proxyen ekte token.
proxy/proxy.go matcher eksakt plassholder etter Bearer-prefiks i autorisert
Authorization-header for konfigurert destinasjon. Regelen aktiverer TLS-
inspeksjon; agenten får offentlig CA/bundle montert ro. Dette kan derfor
håndtere Bedrock-bearer-headeren uten Bedrock-spesifikk nøkkelutskifting.
Region/provider/modell og riktige endepunkter må konfigureres i verktøyet;
Agentbox setter ikke disse automatisk og oversetter ikke API-protokoller.
AWS SigV4 er en annen autentiseringsform og dekkes ikke av enkel bearer-
utskifting. Browser/device-login er også separat fra tokenvariabelen.

## Avgrensning og neste beslutning

Funnene viser dokumentert støtte i dagens upstream og en eksisterende
utskiftingsmekanisme i Agentbox. Det er ikke bevis for ende-til-ende-støtte
med våre pinnede Codex/OpenCode/Claude Code-versjoner. Klientens aksept av
plassholder, proxy/CA, modellvalg, nødvendige destinasjoner og AWS-streaming
må verifiseres senere, etter at brukerflyten er avklart.

login-api-key sender ekte nøkkel til codex login via stdin og går utenom
proxybeskyttelsen. Den trengs ikke for den beskrevne bearer-flyten. Fjerning
av kommandoen er foreløpig et forslag, ikke en vedtatt kodeendring.
