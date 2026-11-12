import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from actualizar_precios import coincide_producto, obtener_precio_html, actualizar, precio_clp

P={"id":"prayanol","medicamento_id":"prayanol","farmacia":"Farmacia ficticia","farmacia_id":"x","modalidad":"internet","url":"https://example.invalid","marca_esperada":"prayanol","dosis_mg":100,"unidades":30}
HTML='<script type="application/ld+json">{"@type":"Product","name":"Prayanol 100 mg x 30 cápsulas","offers":{"priceCurrency":"CLP","price":"15311"}}</script>'
class TestActualizar(unittest.TestCase):
    def test_identidad(self):
        self.assertTrue(coincide_producto("Prayanol 100 mg x 30 cápsulas",P))
        for name in ["Elbrus 1 mg x 30 comprimidos","Prayanol 50 mg x 30","Prayanol 100 mg x 60"]:
            self.assertFalse(coincide_producto(name,P))
    def test_json_ld(self):
        self.assertEqual(obtener_precio_html(HTML,P),(15311,"jsonld_product_offers"))
    def test_precio(self):
        self.assertEqual(precio_clp("$24.464"),24464)
        self.assertIsNone(precio_clp("CLP 0"))
    def test_fecha_historica(self):
        old={"precios":[{"source_id":"prayanol","value":15000,"date":"2026-10-01","captured_at":"2026-10-01T00:00:00Z"}]}
        def falla(cfg): raise RuntimeError("fuente caída")
        r=actualizar({"productos":[P]},old,falla,now="2026-11-12T10:00:00Z")
        self.assertEqual(r["fuentes_comprobadas_esta_ejecucion"],0)
        self.assertEqual(r["precios"][0]["date"],"2026-10-01")
        self.assertEqual(r["precios"][0]["status"],"historico_sin_actualizar")
    def test_captura_simulada_no_publicada(self):
        r=actualizar({"productos":[P]},{},lambda cfg:(15311,"jsonld","https://example.invalid"),now="2026-11-12T10:00:00Z")
        self.assertEqual(r["precios"][0]["value"],15311)
        self.assertEqual(r["fuentes_comprobadas_esta_ejecucion"],1)
    def test_cambio_anomalo(self):
        old={"precios":[{"source_id":"prayanol","value":15000,"date":"2026-10-01"}]}
        r=actualizar({"productos":[P]},old,lambda cfg:(1000,"jsonld","x"),now="2026-11-12T10:00:00Z")
        self.assertEqual(r["precios"][0]["value"],15000)
        self.assertEqual(r["fuentes_comprobadas_esta_ejecucion"],0)
if __name__=="__main__":unittest.main()
