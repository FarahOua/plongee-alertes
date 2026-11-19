"""Backend Flask des alertes plongée."""
import os

# Certificats HTTPS : utiliser le magasin de confiance du système (Windows, macOS, Linux)
# plutôt que celui de Python. Indispensable quand un antivirus, un proxy d'entreprise ou un
# VPN inspecte le trafic HTTPS avec son propre certificat (« self-signed certificate in
# certificate chain »). Sans le paquet truststore, on garde le comportement par défaut.
if os.environ.get("USE_SYSTEM_CERTS", "1") != "0":
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass
