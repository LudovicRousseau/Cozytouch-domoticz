#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Script Cozytouch pour Domoticz
# Auteur : OBone
# review: Yannig Nov 2018
# modification : sg2 Fev 2019

# modification : OBone 2019
# Ajout classe ['DHWP_THERM_V2_MURAL_IO']="io:AtlanticDomesticHotWaterProductionV2_MURAL_IOComponent"
# info: DHWP = Domestic Hot Water Production

# modification : allstar71 10/21 : Correction authentification/connexion suite MAJ serveur
# modification : OBone 11/21 : Ajout 'io:AtlanticPassAPCHeatPumpMainComponent','io:AtlanticPassAPCHeatingAndCoolingZoneComponent','io:AtlanticPassAPCOutsideTemperatureSensor','io:AtlanticPassAPCZoneTemperatureSensor','io:TotalElectricalEnergyConsumptionSensor'.
# modification : tatrox 01/22 : ajout consigne de dérogation pour les radiateurs électriques
# modification : tatrox 01/22 : Ajout classe ['DHWP_THERM_V4_CETHI_IO']="io:AtlanticDomesticHotWaterProductionV2_CETHI_V4_IOComponent" (chauffe eau thermodynamique Atlantic Calypso)
# modification : 5.35 : tatrox 06/23 : changements adresse API et lecture des données renvoyées

# TODO list:
# Prise en compte du mode dérogation sur les AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent
# Affichage du mode éco ou confort sur les AtlanticPassAPCZoneControlZoneComponent (en mode prog sur lez zones)

# En TEST :
# RADIATEUR : MODIFIER LA FONCTION GESTION CONSIGNE POUR SORTIR LE CALCUL DE LA TEMP ECO
# PAC : AJOUTER LE MODE ECO OU CONFORT EN MODE PROG SUR LES ZONES

import requests, shelve, json, time, unicodedata, os, sys, errno
import ma_config


"""
Paramètres
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""
version = 5.35

debug = 2  # 0 : pas de traces debug / 1 : traces requêtes http / 2 : dump data json reçues du serveur cozytouch


"""
Commentaires
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ce script permet de récupérer les données d'un compte Cozytouch stockées
sur le cloud Atlantic, et de les synchroniser avec des capteurs virtuels
domoticz

Etapes du script :
- Au démarrage, on établit la connexion TLS avec le serveur

- On interroge le serveur via une requete GET avec l'identifiant de
  session (cookie transmis préalablement par le serveur lors de
  l'identification)
    - Si la réponse est OK (200): on lance les interrogations pour
      rafraichir les devices et on transmet le tout à Domoticz
    - Si la réponse est NOK (autre que 200) : on tente une connexion
      avec une requete POST avec les identifiants, une fois connecté, on
      sauvegarde l'identificant de session transmis par le serveur
      (cookie) pour les futures interrogations.

- Ensuite on scanne les devices contenus dans l'api cozytouch, on ne
  retient que les devices dont l'url contient un '#1' (device principal)
- Si le device est connu via son nom de classe, on créé un dictionnaire
  contenant ses données
- On ajoute les dictionnaires à une liste que l'on balaye et compare aux
  devices de l'api Cozytouch à chaque démarrage """

"""
Variables globlales
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

global url_cozytouchlog, url_cozytouch, url_atlantic, cookies, cozytouch_save, current_path

url_cozytouchlog = "https://ha110-1.overkiz.com/enduser-mobile-web/enduserAPI/"
url_cozytouch = "https://ha110-1.overkiz.com/enduser-mobile-web/externalAPI/json/"
url_atlantic = "https://apis.groupe-atlantic.com"

current_path = os.path.dirname(os.path.abspath(__file__))  # repertoire actuel
cozytouch_save = current_path + "/cozytouch_save"



"""
**********************************************************
Fonctions génériques
**********************************************************
"""


def var_save(var, var_str):
    """Fonction de sauvegarde
    var: valeur à sauvegarder, var_str: nom objet en mémoire
    """
    d = shelve.open(cozytouch_save)
    if var_str in d:
        d[var_str] = var

    else:
        d[var_str] = 0  # init variable
        d[var_str] = var

    d.close()


def var_restore(var_str, format_str=False):
    """Fonction de restauration
    var_str: nom objet en mémoire
    """
    d = shelve.open(cozytouch_save)
    if not (var_str) in d:
        if format_str:
            value = "init"  # init variable
        else:
            value = 0  # init variable
    else:
        value = d[var_str]
    d.close()
    return value


def http_error(code_erreur, texte_erreur):
    """Evaluation des exceptions HTTP"""
    print(("Erreur HTTP " + str(code_erreur) + " : " + texte_erreur))


"""
**********************************************************
Fonctions Cozytouch
**********************************************************
"""


def cozytouch_login(login, password):

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic Q3RfMUpWeVRtSUxYOEllZkE3YVVOQmpGblpVYToyRWNORHpfZHkzNDJVSnFvMlo3cFNKTnZVdjBh",
    }
    data = {
        "grant_type": "password",
        "username": "GA-PRIVATEPERSON/" + login,
        "password": password,
    }

    url = url_atlantic + "/token"
    req = requests.post(url, data=data, headers=headers)

    atlantic_token = req.json()["access_token"]

    headers = {"Authorization": "Bearer " + atlantic_token + ""}
    reqjwt = requests.get(url_atlantic + "/magellan/accounts/jwt", headers=headers)

    jwt = reqjwt.content.decode("utf-8").replace('"', "")
    data = {"jwt": jwt}
    jsession = requests.post(url_cozytouchlog + "login", data=data)

    if debug:
        print(
            (
                " POST-> "
                + url_cozytouchlog
                + "login | userId=****&userPassword=**** : "
                + str(jsession.status_code)
            )
        )

    if jsession.status_code == 200:  # Réponse HTTP 200 : OK
        print("Authentification serveur cozytouch OK")
        cookies = dict(
            JSESSIONID=(jsession.cookies["JSESSIONID"])
        )  # Récupération cookie ID de session
        var_save(cookies, "cookies")  # Sauvegarde cookie
        return True

    print("!!!! Echec authentification serveur cozytouch")
    http_error(req.status_code, req.reason)
    return False


def cozytouch_GET(json):
    """Fonction d'interrogation HTTP GET avec l'url par défaut
    json: nom de fonction JSON à transmettre au serveur
    """
    headers = {
        "cache-control": "no-cache",
        "Host": "ha110-1.overkiz.com",
        "Connection": "Keep-Alive",
    }
    myurl = url_cozytouchlog + json
    cookies = var_restore("cookies")
    req = requests.get(myurl, headers=headers, cookies=cookies)
    if debug:
        print(
            ("  ".join(("GET-> ", myurl, " : ", str(req.status_code))).encode("utf-8"))
        )

    if req.status_code == 200:  # Réponse HTTP 200 : OK
        data = req.json()
        return data

    http_error(req.status_code, req.reason)  # Appel fonction sur erreur HTTP
    time.sleep(1)  # Tempo entre requetes
    return None


def decouverte_devices():

    """Fonction de découverte des devices Cozytouch
    Scanne les devices présents dans l'api cozytouch et gère les ajouts à Domoticz
    """
    if debug:
        print("**** Decouverte devices ****")

    # Renvoi toutes les données du cozytouch
    data = cozytouch_GET("setup")

    return data


"""
**********************************************************
Déroulement du script
**********************************************************
"""

def get_data_from_server():
    # Test d'une requete GET pour voir si on peut se connecter avec l'ancien cookie et éviter le login
    print(
        "**** Tentative interrogation serveur Cozytouch sans login, avec cookie login précédent ****"
    )
    if cozytouch_GET("setup"):
        print("Requete de test sans login reussie, bypass login\n")
    else:
        # Tentative de login au serveur Cozytouch
        if debug:
            print(
                "!!!! Echec interrogation serveur Cozytouch sans login, connexion serveur Cozytouch ****"
            )

        if cozytouch_login(ma_config.login, ma_config.password):
            if debug:
                print("Connexion serveur Cozytouch reussie")
        else:
            raise Exception("!!!! Echec connexion serveur Cozytouch")

        # Rafraichissement états
        if cozytouch_GET("setup"):
            print("Requete setup reussie")
        else:
            raise Exception("!!!! Echec requete refreshAllStates")

    time.sleep(2)
    data = decouverte_devices()

    return data

def extract_data_from_json(data):
    fields = ("core:BottomTankWaterTemperatureState",
              "core:RemainingHotWaterState",
              "modbuslink:MiddleWaterTemperatureState",
              "modbuslink:PowerHeatElectricalState")

    devices = data["setup"]["devices"]
    values = dict()
    for device in devices:
        if device["label"] == "LINEO":
            # pp.pprint(device)

            states = device["states"]
            # pp.pprint(states)
            for state in states:
                # pp.pprint(state)
                values[state["name"]] = state["value"]

    # pp.pprint(values)
    output = list()
    for field in fields:
        output.append("{}={}".format(field, values[field]))
    print("ChauffeEau", ",".join(output))

if __name__ == "__main__":
    data = get_data_from_server()

    if debug == 2:
        # dump in a JSON file
        with open("dump_cozytouch.json", "w") as f1:
            f1.write(json.dumps(data, indent=4, separators=(",", ": ")))

    extract_data_from_json(data)
