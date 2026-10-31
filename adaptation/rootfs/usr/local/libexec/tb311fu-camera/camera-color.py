"""Decode sensor-specific Bayer layouts without scene-dependent color gains."""
import numpy as np

BAYER_SITES = {
    'RGGB': ((0, 0), (0, 1), (1, 0), (1, 1)),
    'GRBG': ((0, 1), (0, 0), (1, 1), (1, 0)),
    'GBRG': ((1, 0), (0, 0), (1, 1), (0, 1)),
    'BGGR': ((1, 1), (0, 1), (1, 0), (0, 0)),
}


def decode_raw10(data, width, height, stride, pattern):
    if width % 4 or height % 2 or stride < width * 5 // 4:
        raise ValueError('Unsupported RAW10 image geometry')
    transport = np.frombuffer(data, dtype=np.uint8).reshape(height, stride)
    raw = transport[:, :width * 5 // 4].reshape(height, width // 4, 5)
    raw = raw[:, :, :4].reshape(height, width).astype(np.float32)
    red, green1, green2, blue = BAYER_SITES[pattern]
    plane = lambda site: raw[site[0]::2, site[1]::2]
    return np.stack((plane(red), (plane(green1) + plane(green2)) * .5,
                     plane(blue)), axis=-1)


def render_preview(rgb):
    rgb = np.maximum(rgb - 16, 0)
    level = max(float(np.percentile(rgb[::8, ::8], 98)), 8)
    gamma = np.uint8([(value / 255) ** .45 * 255 for value in range(256)])
    # Gray-world gains make a dominant colored object change the whole image.
    # Keep channel identities and neutral gains until real calibration exists.
    return gamma[np.uint8(np.clip(rgb / level, 0, 1) * 255)]
