try:
    from .ta_engine import TAEngine
    from .masalas import MeanReversionMasala, TrendMasala, MomentumMasala, whale_movement_masala
    from .regime import RegimeClassifier
except ImportError:
    # Open-source build: Suvarn-derived masalas not bundled.
    # simple_ta and backtest are still importable as submodules.
    pass
