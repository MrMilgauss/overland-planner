// A blank 256 x 256 map tile for the browser checks: no test ever fetches a tile from the internet. Whatever the map
// asks of a host other than the planner's own is answered with this PNG.
import { crc32, deflateSync } from 'node:zlib';
import type { Page } from '@playwright/test';

function chunk(type: string, data: Buffer): Buffer {
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const check = Buffer.alloc(4);
  check.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, check]);
}

function blankTile(): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(256, 0);
  header.writeUInt32BE(256, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8 bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(256 * 3, 232)]);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(Buffer.concat(Array.from({ length: 256 }, () => row)))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

export async function serveBlankTiles(page: Page, plannerUrl: string): Promise<void> {
  const body = blankTile();
  const planner = new URL(plannerUrl).origin;
  await page.route(
    (url) => url.origin !== planner,
    (route) => route.fulfill({ status: 200, contentType: 'image/png', body }),
  );
}
