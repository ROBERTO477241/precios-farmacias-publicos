#!/usr/bin/env python3
"""Consulta precios publicados, sin evadir bloqueos ni inventar datos."""
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "fuentes.json"
OUTPUT = ROOT / "docs" / "precios_actualizados.json"
AGENT = "Mozilla/5.0 (compatible; CompararSaludPrecio/1.0; consulta ocasional de precios publicos)"

def normalizar(s):
    value = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(c for c in value if not unicodedata.combining(c))

def coincide_producto(nombre, cfg):
    t = normalizar(nombre)
    marca = normalizar(cfg["marca_esperada"])
    if not re.search(r"(?<![a-z])" + re.escape(marca) + r"(?![a-z])", t):
        return False
    if not re.search(r"(?<!\d)" + str(cfg["dosis_mg"]) + r"\s*mg\b", t):
        return False
    n = str(cfg["unidades"])
    return bool(re.search(r"\b(?:x|por|de)\s*" + n + r"\b",t) or
                re.search(r"\b" + n + r"\s*(?:cap|comprim|tableta)",t))

def precio_clp(value):
    if value is None or isinstance(value,bool): return None
    s = str(value).strip().upper().replace("CLP","").replace("$","").replace(" ","")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
        s=s.replace(".","").replace(",","")
    elif re.fullmatch(r"\d+[.,]\d{1,2}", s):
        s=s.replace(",",".")
    try:
        x=float(s)
        return int(x) if x.is_integer() and 100 <= x <= 2000000 else None
    except ValueError:
        return None

def jsonld_productos(html):
    scripts=re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",html,re.I|re.S)
    def walk(x):
        if isinstance(x,list):
            for v in x: yield from walk(v)
        elif isinstance(x,dict):
            types=x.get("@type",[])
            if isinstance(types,str): types=[types]
            if "Product" in types: yield x
            for k in ("@graph","mainEntity","itemListElement"):
                if k in x: yield from walk(x[k])
    for s in scripts:
        try: yield from walk(json.loads(s))
        except (ValueError,TypeError): continue

def obtener_precio_html(html,cfg):
    for p in jsonld_productos(html):
        if not coincide_producto(p.get("name",""),cfg): continue
        offers=p.get("offers",[])
        if isinstance(offers,dict): offers=[offers]
        values=[]
        for o in offers:
            if not isinstance(o,dict):continue
            currency=o.get("priceCurrency",p.get("priceCurrency"))
            if currency and str(currency).upper()!="CLP":continue
            value=precio_clp(o.get("price"))
            if value is not None:values.append(value)
        if len(set(values))==1: return values[0],"jsonld_product_offers"
    return None,None

def obtener_url(url):
    req=Request(url,headers={"User-Agent":AGENT,"Accept":"text/html,application/json"})
    with urlopen(req,timeout=20) as res:
        if res.status!=200:raise ValueError("HTTP no exitoso")
        return res.read(2000000).decode("utf-8","replace"),res.geturl()

def obtener_precio(cfg):
    html,url=obtener_url(cfg["url"])
    value,method=obtener_precio_html(html,cfg)
    if value is not None:return value,method,url
    if "/products/" in cfg["url"]:
        endpoint=cfg["url"].split("?",1)[0].rstrip("/")+".js"
        try:
            raw,_=obtener_url(endpoint)
            p=json.loads(raw)
            if coincide_producto(p.get("title",""),cfg):
                v=p.get("variants",[])
                v=[x for x in v if x.get("available") is not False]
                if len(v)==1 and type(v[0].get("price")) is int:
                    cents=v[0]["price"]
                    if cents%100==0 and precio_clp(cents//100) is not None:
                        return cents//100,"shopify_variant_price_cents",url
        except Exception: pass
    raise ValueError("No se validó precio CLP del medicamento y presentación exactos")

def actualizar(entrada,previo,fetcher=obtener_precio,now=None):
    now=now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    previous={p["source_id"]:p for p in previo.get("precios",[]) if isinstance(p,dict) and p.get("source_id")}
    output=[]; errors=[]; count=0
    for cfg in entrada["productos"]:
        old=previous.get(cfg["id"])
        try:
            value,method,url=fetcher(cfg)
            if precio_clp(value) is None:raise ValueError("Precio fuera de rango")
            if old and old.get("value") and abs(value-old["value"])/old["value"] > .5:
                raise ValueError("Cambio superior a 50%; exige verificación")
            output.append({"id":10000+int(hashlib.sha256(cfg["id"].encode()).hexdigest()[:12],16),
                           "source_id":cfg["id"],"med":cfg["medicamento_id"],
                           "farm":cfg["farmacia_id"],"name":cfg["farmacia"],"mode":cfg["modalidad"],
                           "value":value,"date":now[:10],"captured_at":now,"link":url,
                           "terms":"Precio web publicado; no incluye despacho ni beneficios personales",
                           "grade":"fuente_directa_auto","status":"capturado","method":method})
            count+=1
        except Exception as exc:
            errors.append({"fuente":cfg["id"],"motivo":str(exc)[:180]})
            if old:
                saved=dict(old);saved["status"]="historico_sin_actualizar"
                output.append(saved)
    return {"schema_version":1,"generado_en":now,
            "fuentes_comprobadas_esta_ejecucion":count,"fuentes_intentadas":len(entrada["productos"]),
            "precios":output,"errores":errors}

def main():
    source=json.loads(SOURCE.read_text(encoding="utf-8"))
    previous=json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    result=actualizar(source,previous)
    print(json.dumps({"obtenidos":result["fuentes_comprobadas_esta_ejecucion"],
                      "intentados":result["fuentes_intentadas"],"errores":result["errores"]},
                      ensure_ascii=False,indent=2))
    if result["fuentes_comprobadas_esta_ejecucion"]==0:
        print("FALLO: ninguna lectura de precio real validada; no se publica.",file=sys.stderr)
        return 1
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return 0

if __name__=="__main__":sys.exit(main())
