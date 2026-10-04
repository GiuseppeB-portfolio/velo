# Sicurezza

velo tratta dati personali, quindi le segnalazioni di sicurezza sono benvenute.

## Come segnalare un problema

Usa la segnalazione privata di GitHub: scheda **Security** del repository, poi **Report a vulnerability**. Così il problema non è pubblico finché non è risolto.

**Non allegare mai file con dati reali**, né dizionari di ripristino (`*.velo-map.json`) o chiavi (`project.key`). Se serve un esempio, costruiscilo con dati inventati.

## Cosa rientra

- Un modo per far uscire dati dal computer (richieste di rete, file lasciati in cartelle accessibili).
- Un modo per raggiungere il server locale da un altro sito o da un'altra macchina.
- Dati originali che restano nel file pseudonimizzato in un campo che l'utente ha scelto.
- Un ripristino che restituisce valori diversi dagli originali.

## Cosa è già documentato come limite

I limiti dichiarati nel [README](README.md#limiti) non sono vulnerabilità: per esempio che i campi non scelti e il testo libero restano in chiaro, o che il risultato è una pseudonimizzazione e non un'anonimizzazione.

## Versioni

È una pre-release (0.1): le correzioni vanno sull'ultima versione.
