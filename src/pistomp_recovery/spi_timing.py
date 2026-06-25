"""SPI display transfer-cost model.

Ported from ``../pi-stomp/uilib/spi_timing.py``. One source of truth for
"how long does it take to push N pixels at this SPI clock", used by the
inline-vs-coalesce gate in :class:`RecoveryAppCore` (small dirty clips push
inline; large clips coalesce into one deferred flush).

The push cost is affine:

    fixed per-call  +  clock-independent per-pixel  +  bits-on-the-wire / clock

The constants are fit from on-device timing of an ILI9341 ``update()`` at
20 MHz, 33.3 MHz, and 50 MHz actual (Pi 5 / Python 3.14). They hold within
~1% across all three clocks and the full size range.
"""

from __future__ import annotations

# Wire bits per pixel: 16 (RGB565). The fit converges very close to 16,
# confirming negligible framing overhead at these clock speeds.
BITS_PER_PIXEL: float = 16.0071

# Clock-independent per-pixel cost: numpy 565 packing + driver. Doesn't get
# cheaper with a faster clock, so it floors how fast large pushes can go.
PIPELINE_MS_PER_PX: float = 5.856e-05

# Fixed per-call cost: address-window commands + Python/driver call overhead.
FIXED_MS: float = 0.7117


def transfer_ms(pixels: int, spi_hz: float) -> float:
    """Estimated milliseconds to push ``pixels`` to an SPI display at ``spi_hz``."""
    wire_ms: float = pixels * BITS_PER_PIXEL / spi_hz * 1000
    return FIXED_MS + pixels * PIPELINE_MS_PER_PX + wire_ms
