"""Tests unitarios de sync/bq_io.py que NO requieren GCP ni credenciales:
solo las funciones puras (MERGE SQL, resolucion de tablas, conversion de
DataFrames, parsing de refresh_order, tipado de parametros).

    python -m pytest sync/tests -q
"""
import os
import sys
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import bq_io  # noqa: E402


# ---------------------------------------------------------------- resolve_table

def test_resolve_table_dim_va_a_afp_dim():
    assert bq_io.resolve_table('dim_bd_funds') == f'{bq_io.PROJECT_ID}.{bq_io.DATASET_DIM}.dim_bd_funds'


def test_resolve_table_resto_va_a_afp_raw():
    assert bq_io.resolve_table('chist_adjusted') == f'{bq_io.PROJECT_ID}.{bq_io.DATASET_RAW}.chist_adjusted'
    assert bq_io.resolve_table('ipd_cartera_eom') == f'{bq_io.PROJECT_ID}.{bq_io.DATASET_RAW}.ipd_cartera_eom'


def test_resolve_table_respeta_nombres_calificados():
    assert bq_io.resolve_table('afp_mart.mv_aum') == f'{bq_io.PROJECT_ID}.afp_mart.mv_aum'
    assert bq_io.resolve_table('otro-proyecto.ds.tabla') == 'otro-proyecto.ds.tabla'


def test_resolve_table_override_alt_datasets(monkeypatch):
    monkeypatch.setitem(bq_io.ALT_DATASETS, 'dim_especial', 'afp_mart')
    assert bq_io.resolve_table('dim_especial') == f'{bq_io.PROJECT_ID}.afp_mart.dim_especial'


def test_defaults_de_configuracion():
    # Constantes del plan (§9): se leen de env con estos defaults.
    assert bq_io.PROJECT_ID == os.getenv('GCP_PROJECT_ID', 'pat-uat-global')
    assert bq_io.LOCATION == os.getenv('BQ_LOCATION', 'southamerica-west1')
    assert bq_io.ALTERNATIVES_MARTS == ['mv_chist_aa', 'mv_aum', 'mv_strategy_afp_ow_uw']


# ---------------------------------------------------------------- MERGE SQL

def test_build_merge_sql_update_todas_las_no_clave_e_insert_explicito():
    sql = bq_io.build_merge_sql('p.afp_raw.tipo_cambio', 'p.afp_stg.tipo_cambio_abc',
                                ['fecha', 'instrumento_codigo', 'valor'],
                                ['fecha', 'instrumento_codigo'])
    assert sql.startswith('MERGE `p.afp_raw.tipo_cambio` T\nUSING `p.afp_stg.tipo_cambio_abc` S\n')
    assert 'ON T.`fecha` = S.`fecha` AND T.`instrumento_codigo` = S.`instrumento_codigo`' in sql
    assert 'WHEN MATCHED THEN UPDATE SET `valor` = S.`valor`' in sql
    # las claves NO se actualizan
    assert '`fecha` = S.`fecha`' not in sql.split('WHEN MATCHED')[1].split('WHEN NOT MATCHED')[0]
    assert ('WHEN NOT MATCHED THEN INSERT (`fecha`, `instrumento_codigo`, `valor`) '
            'VALUES (S.`fecha`, S.`instrumento_codigo`, S.`valor`)') in sql


def test_build_merge_sql_sin_columnas_no_clave_omite_update():
    sql = bq_io.build_merge_sql('p.d.t', 'p.s.t_x', ['a', 'b'], ['a', 'b'])
    assert 'WHEN MATCHED' not in sql
    assert 'WHEN NOT MATCHED THEN INSERT (`a`, `b`) VALUES (S.`a`, S.`b`)' in sql


def test_build_merge_sql_clave_ausente_falla():
    with pytest.raises(ValueError):
        bq_io.build_merge_sql('p.d.t', 'p.s.t_x', ['a', 'b'], ['zzz'])


def test_conflict_list_acepta_string_y_lista():
    assert bq_io._conflict_list('fecha, afp') == ['fecha', 'afp']
    assert bq_io._conflict_list(['nemo']) == ['nemo']


# ---------------------------------------------------------------- prepare_dataframe

def test_prepare_dataframe_fechas_a_date_y_nan_a_none():
    df = pd.DataFrame({
        'fecha': pd.to_datetime(['2025-01-31', None]),
        'afp': ['HABITAT', np.nan],
        'valor': [1.5, np.nan],
        'n': [1, 2],
    })
    out = bq_io.prepare_dataframe(df)
    assert list(out.columns) == ['fecha', 'afp', 'valor', 'n']      # nombres intactos
    assert out['fecha'].tolist() == [date(2025, 1, 31), None]        # datetime -> date, NaT -> None
    assert out['afp'].tolist() == ['HABITAT', None]                  # NaN en texto -> None
    assert out['valor'].dtype == 'float64' and np.isnan(out['valor'].iloc[1])  # float NaN -> NULL en parquet
    assert out['n'].tolist() == [1, 2]
    assert df['fecha'].dtype.kind == 'M'                             # el original no se modifica


def _field(name, ftype, scale=None):
    from google.cloud import bigquery
    kw = {'scale': scale} if scale is not None else {}
    return bigquery.SchemaField(name, ftype, **kw)


def test_prepare_dataframe_alinea_al_esquema_destino():
    df = pd.DataFrame({
        'id': [1.0, np.nan],                 # float con NaN -> INT64 nullable
        'ratio': [1, 2],                     # int -> FLOAT64
        'monto': [1234.5678, np.nan],        # -> NUMERIC(38,9) Decimal
        'mes': ['2025-01-01', None],         # string ISO -> DATE
        'flag': [1, 0],                      # 0/1 -> BOOL
        'codigo': [45102010.0, np.nan],      # float -> STRING
        'extra': pd.to_datetime(['2025-02-28', '2025-03-31']),  # no esta en la tabla: regla generica
    })
    schema = [_field('id', 'INTEGER'), _field('ratio', 'FLOAT'), _field('monto', 'NUMERIC'),
              _field('mes', 'DATE'), _field('flag', 'BOOLEAN'), _field('codigo', 'STRING')]
    out = bq_io.prepare_dataframe(df, schema)
    assert str(out['id'].dtype) == 'Int64' and out['id'].iloc[0] == 1 and pd.isna(out['id'].iloc[1])
    assert out['ratio'].dtype == 'float64'
    assert out['monto'].iloc[0] == Decimal('1234.567800000') and out['monto'].iloc[1] is None
    assert out['mes'].tolist() == [date(2025, 1, 1), None]
    assert str(out['flag'].dtype) == 'boolean' and out['flag'].tolist() == [True, False]
    assert out['codigo'].tolist() == ['45102010.0', None]
    assert out['extra'].tolist() == [date(2025, 2, 28), date(2025, 3, 31)]


# ---------------------------------------------------------------- parametros DELETE

def test_infer_param_type_fechas_como_date():
    t, vals = bq_io.infer_param_type([date(2025, 1, 31), pd.Timestamp('2025-02-28'), '2025-03-31'])
    assert t == 'DATE'
    assert vals == ['2025-01-31', '2025-02-28', '2025-03-31']


def test_infer_param_type_numeros_y_strings():
    assert bq_io.infer_param_type([1, np.int64(2)]) == ('INT64', [1, 2])
    assert bq_io.infer_param_type([1, 2.5]) == ('FLOAT64', [1.0, 2.5])
    assert bq_io.infer_param_type(['2025-01', 'x']) == ('STRING', ['2025-01', 'x'])


# ---------------------------------------------------------------- marts

def test_parse_refresh_order():
    txt = """
    # orden de dependencia
    mv_chist_aa.sql
    mv_aum          # snapshot AUM

    mv_strategy_afp_ow_uw
    mv_aum
    """
    assert bq_io.parse_refresh_order(txt) == ['mv_chist_aa', 'mv_aum', 'mv_strategy_afp_ow_uw']


def test_render_mart_sql_sustituye_placeholders():
    sql = "CREATE OR REPLACE TABLE `${project}.${mart}.mv_aum` AS SELECT * FROM `${project}.${raw}.t` JOIN `${project}.${dim}.d` USING (k) -- ${ops} ${otro}"
    out = bq_io.render_mart_sql(sql, project='p', raw='r', dim='d', mart='m', ops='o')
    assert out == "CREATE OR REPLACE TABLE `p.m.mv_aum` AS SELECT * FROM `p.r.t` JOIN `p.d.d` USING (k) -- o ${otro}"


def test_list_marts_orden_y_extras(tmp_path):
    (tmp_path / 'refresh_order.txt').write_text('b\na\n', encoding='utf-8')
    for n in ('a', 'b', 'c'):
        (tmp_path / f'{n}.sql').write_text('SELECT 1', encoding='utf-8')
    assert bq_io.list_marts(tmp_path) == ['b', 'a', 'c']


def test_refresh_marts_ejecuta_en_orden_con_cliente_falso(tmp_path):
    (tmp_path / 'refresh_order.txt').write_text('mv_chist_aa\nmv_aum\nmv_strategy_afp_ow_uw\n', encoding='utf-8')
    for n in bq_io.ALTERNATIVES_MARTS:
        (tmp_path / f'{n}.sql').write_text(f'CREATE OR REPLACE TABLE `${{project}}.${{mart}}.{n}` AS SELECT 1', encoding='utf-8')

    class _Job:
        def result(self):
            return None

    class FakeClient:
        def __init__(self):
            self.sqls = []

        def query(self, sql, job_config=None):
            self.sqls.append(sql)
            return _Job()

    c = FakeClient()
    done = bq_io.refresh_marts(c, ['mv_aum', 'mv_chist_aa'], marts_dir=tmp_path)
    assert done == ['mv_chist_aa', 'mv_aum']        # orden global, no el pedido
    assert c.sqls[0] == f'CREATE OR REPLACE TABLE `{bq_io.PROJECT_ID}.{bq_io.DATASET_MART}.mv_chist_aa` AS SELECT 1'
    with pytest.raises(FileNotFoundError):
        bq_io.refresh_marts(c, ['no_existe'], marts_dir=tmp_path)
