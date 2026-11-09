"""The 68 named Western Alps places of the I1/I2 generator (Piedmont, Aosta Valley, Hautes-Alpes; spike findings.md).

The places the scenarios already name come from `steps/places.py` (one definition each); only the missing ones are
added here. Left out of PLACES: the Dolomites, and "Hotel Sestriere" / "Rifugio Pian dell'Alpe", which share their
coordinates with "Sestriere" / "Pian dell'Alpe" and would give duplicate stops. Coordinates are the town centre or the
pass, to 4 decimals. Names stay ASCII and free of XML specials: each track's name is written into its GPX file.
"""

from __future__ import annotations

from tests.acceptance.overland_route_planner_mvp.steps.places import PLACES, Place

FROM_THE_SCENARIOS = (
    "Casa Marco, Torino",
    "Briancon",
    "Sestriere",
    "Pian dell'Alpe",
    "Bardonecchia",
    "Aosta",
    "Cuneo",
)

ADDED = (
    # Piedmont
    Place("Susa", 45.1383, 7.0500),
    Place("Oulx", 45.0330, 6.8330),
    Place("Cesana Torinese", 44.9530, 6.7930),
    Place("Claviere", 44.9380, 6.7520),
    Place("Sauze d'Oulx", 45.0270, 6.8590),
    Place("Fenestrelle", 45.0350, 7.0500),
    Place("Pragelato", 45.0150, 6.9420),
    Place("Pinerolo", 44.8850, 7.3310),
    Place("Perosa Argentina", 44.9580, 7.1920),
    Place("Bobbio Pellice", 44.8070, 7.1170),
    Place("Torre Pellice", 44.8200, 7.2180),
    Place("Avigliana", 45.0790, 7.3970),
    Place("Giaveno", 45.0420, 7.3520),
    Place("Lanzo Torinese", 45.2750, 7.4800),
    Place("Balme", 45.3020, 7.2190),
    Place("Usseglio", 45.2330, 7.2190),
    Place("Ceresole Reale", 45.4330, 7.2330),
    Place("Locana", 45.4170, 7.4580),
    Place("Pont Canavese", 45.4210, 7.6000),
    Place("Ivrea", 45.4670, 7.8760),
    Place("Saluzzo", 44.6450, 7.4920),
    Place("Paesana", 44.6830, 7.2750),
    Place("Crissolo", 44.7000, 7.1580),
    Place("Sampeyre", 44.5800, 7.1880),
    Place("Casteldelfino", 44.5900, 7.0700),
    Place("Chianale", 44.6460, 6.9930),
    Place("Dronero", 44.4670, 7.3670),
    Place("Acceglio", 44.4750, 6.9900),
    Place("Demonte", 44.3150, 7.2950),
    Place("Vinadio", 44.3060, 7.1760),
    Place("Argentera", 44.3970, 6.9370),
    Place("Limone Piemonte", 44.2000, 7.5760),
    Place("Borgo San Dalmazzo", 44.3330, 7.4870),
    Place("Entracque", 44.2400, 7.3970),
    # Aosta Valley
    Place("Courmayeur", 45.7960, 6.9690),
    Place("La Thuile", 45.7130, 6.9520),
    Place("Morgex", 45.7580, 7.0410),
    Place("Cogne", 45.6080, 7.3560),
    Place("Valsavarenche", 45.5920, 7.2100),
    Place("Rhemes-Notre-Dame", 45.5700, 7.1180),
    Place("Valgrisenche", 45.6300, 7.0640),
    Place("Saint-Vincent", 45.7500, 7.6500),
    Place("Breuil-Cervinia", 45.9330, 7.6300),
    Place("Gressoney-Saint-Jean", 45.7760, 7.8260),
    Place("Champoluc", 45.8320, 7.7270),
    Place("Bard", 45.6090, 7.7450),
    Place("Etroubles", 45.8200, 7.2300),
    Place("Colle del Gran San Bernardo", 45.8690, 7.1710),
    # Hautes-Alpes
    Place("Montgenevre", 44.9310, 6.7240),
    Place("Nevache", 45.0200, 6.6040),
    Place("Le Monetier-les-Bains", 44.9760, 6.5090),
    Place("L'Argentiere-la-Bessee", 44.7930, 6.5560),
    Place("Vallouise", 44.8460, 6.4890),
    Place("Guillestre", 44.6600, 6.6490),
    Place("Abries", 44.7960, 6.9280),
    Place("Ceillac", 44.6670, 6.7790),
    Place("Saint-Veran", 44.7020, 6.8680),
    Place("Embrun", 44.5640, 6.4950),
    Place("Col du Lautaret", 45.0350, 6.4040),
    Place("Col de l'Izoard", 44.8200, 6.7350),
    Place("La Grave", 45.0450, 6.3060),
)

WESTERN_ALPS: tuple[Place, ...] = (*(PLACES[name] for name in FROM_THE_SCENARIOS), *ADDED)

assert len(WESTERN_ALPS) == 68, f"{len(WESTERN_ALPS)} places, the method uses 68"
assert len({p.name for p in WESTERN_ALPS}) == len({(p.lat, p.lon) for p in WESTERN_ALPS}) == 68, "a place twice"
