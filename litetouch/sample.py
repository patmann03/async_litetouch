import asyncio
import logging

# Adjust import to wherever you placed the class
# from litetouch_rtc import LiteTouchClient
from litetouch_rtc import LiteTouchClient


def int_auto(token: str) -> int:
    """
    Parse a numeric token that may be decimal ('90') or hex ('E2').
    Handles -1.
    """
    t = token.strip()
    if t.startswith("-"):
        return int(t)
    try:
        return int(t)          # decimal
    except ValueError:
        return int(t, 16)      # hex


def normalize_to_pct(v: int) -> int:
    """
    Normalize to 0..100 if controller returns 0..255 (e.g., E2=226).
    """
    if v < 0:
        return v
    if v > 100:
        return round(v * 100 / 255)
    return v


async def dgmlv_levels_safe(client: LiteTouchClient, module_hex: str) -> list[int]:
    """
    Send DGMLV and parse raw levels WITHOUT using client.get_module_levels()
    (avoids int('E2') parsing failures if your controller returns hex tokens).
    DGMLV return: R,RQRES,DGMLV,<map>,<level1>..<level8>  [2](https://outlook.office365.com/owa/?ItemID=AQMkAGFkN2ViMWQ4LTQ1NDYtNGZjNC05NjNkLWI5MjZhM2M2MGM2OABGAAADiVghTn%2bQKEWFk2Dg67dNYQcAP3iPIHG7hEu6G9CFycZ39wAAAgEJAAAAP3iPIHG7hEu6G9CFycZ39wAF9Zc7WAAAAA%3d%3d&exvsurl=1&viewmodel=ReadMessageItem)[1](https://github.com/patmann03/custom_components/blob/master/info.md)
    """
    # Use the underlying transport request to get the raw response
    t = client._pick_cmd_transport()  # internal helper; fine for a test script
    resp = await t.request(
        client._cmd("R", "DGMLV", module_hex),
        expect=client._expect_query("DGMLV"),
        timeout=3.0,
    )

    # resp.fields: [map, level1, level2, ...]
    if not resp.fields:
        return [0] * 8

    raw_level_tokens = resp.fields[2:]  # skip the map
    currmap = resp.fields[1:2]
    print(currmap)
    levels = [normalize_to_pct(int_auto(str(x))) for x in raw_level_tokens[:9]]
    levels += [0] * (8 - len(levels))
    return levels


async def main():
    # ---- CONFIG ----
    HOST = "10.3.1.35"
    PORT = 10001

    LOAD_GROUP_ID = 135      # <-- change to your load group to test
    INIT_LEVEL_PCT = 30     # <-- initializes load group members to this level (0..100)

    MODULE_HEX = "0007"     # module 7 as 4-digit hex
    OUTPUT_INDEX = 6        # "load 7" as output index 7 (bitmap 0x80)
    TARGET_LEVEL_PCT = 25   # set that output to 50%

    FADE_SECONDS = 3

    # If you meant "7th output" in human counting (1..8), use:
    # OUTPUT_INDEX = 6

    # ---- CONNECT ----
    client = LiteTouchClient(
        HOST,
        PORT,
        command_connections=4,               # 4 concurrent command sockets
        use_separate_event_connection=True,  # optional but recommended
        print_raw=True
    )

    await client.start()

    try:
        # 1) Turn load group ON: R,CSLON,<load group>  [2](https://outlook.office365.com/owa/?ItemID=AQMkAGFkN2ViMWQ4LTQ1NDYtNGZjNC05NjNkLWI5MjZhM2M2MGM2OABGAAADiVghTn%2bQKEWFk2Dg67dNYQcAP3iPIHG7hEu6G9CFycZ39wAAAgEJAAAAP3iPIHG7hEu6G9CFycZ39wAF9Zc7WAAAAA%3d%3d&exvsurl=1&viewmodel=ReadMessageItem)[1](https://github.com/patmann03/custom_components/blob/master/info.md)
        print(f"Turning load group {LOAD_GROUP_ID} ON...")
        #await client.set_loads_on(LOAD_GROUP_ID)

        #await asyncio.sleep(2)

        # 2) Initialize load levels for that group: R,CINLL,<loadgroupid>,<value>  [2](https://outlook.office365.com/owa/?ItemID=AQMkAGFkN2ViMWQ4LTQ1NDYtNGZjNC05NjNkLWI5MjZhM2M2MGM2OABGAAADiVghTn%2bQKEWFk2Dg67dNYQcAP3iPIHG7hEu6G9CFycZ39wAAAgEJAAAAP3iPIHG7hEu6G9CFycZ39wAF9Zc7WAAAAA%3d%3d&exvsurl=1&viewmodel=ReadMessageItem)[1](https://github.com/patmann03/custom_components/blob/master/info.md)
        print(f"Initializing load group {LOAD_GROUP_ID} to {INIT_LEVEL_PCT}%...")
        await client.initialize_load_levels(LOAD_GROUP_ID, INIT_LEVEL_PCT)

        #await asyncio.sleep(2)

        # 3) Turn load group OFF: R,CSLOF,<load group>  [2](https://outlook.office365.com/owa/?ItemID=AQMkAGFkN2ViMWQ4LTQ1NDYtNGZjNC05NjNkLWI5MjZhM2M2MGM2OABGAAADiVghTn%2bQKEWFk2Dg67dNYQcAP3iPIHG7hEu6G9CFycZ39wAAAgEJAAAAP3iPIHG7hEu6G9CFycZ39wAF9Zc7WAAAAA%3d%3d&exvsurl=1&viewmodel=ReadMessageItem)[1](https://github.com/patmann03/custom_components/blob/master/info.md)
        print(f"Turning load group {LOAD_GROUP_ID} OFF...")
        #await client.set_loads_off(LOAD_GROUP_ID)

        #await asyncio.sleep(2)

        # 4) Set module 7 output 7 to 50% via DGMLV + DSMLV
        #    DGMLV gets current levels. DSMLV sets selected loads on a module.  [2](https://outlook.office365.com/owa/?ItemID=AQMkAGFkN2ViMWQ4LTQ1NDYtNGZjNC05NjNkLWI5MjZhM2M2MGM2OABGAAADiVghTn%2bQKEWFk2Dg67dNYQcAP3iPIHG7hEu6G9CFycZ39wAAAgEJAAAAP3iPIHG7hEu6G9CFycZ39wAF9Zc7WAAAAA%3d%3d&exvsurl=1&viewmodel=ReadMessageItem)[1](https://github.com/patmann03/custom_components/blob/master/info.md)
        print(f"Reading module {MODULE_HEX} levels (safe parse)...")
        levels = await dgmlv_levels_safe(client, MODULE_HEX)
        print(f"Current levels: {levels}")

        # Update just the target output in the cached list
        levels[OUTPUT_INDEX] = TARGET_LEVEL_PCT

        # DSMLV bitmap selects which output changes
        # output index 7 => 1<<7 => 0x80
        map_hex = f"{(1 << OUTPUT_INDEX):02X}"

        print(f"Setting module {MODULE_HEX} output index {OUTPUT_INDEX} to {TARGET_LEVEL_PCT}% (map={map_hex})...")
        # await client.set_module_levels(
        #     module_hex=MODULE_HEX,
        #     bitmap_hex='FF',#map_hex,
        #     time_seconds=FADE_SECONDS,
        #     levels=levels
        # )

        print("Done. Reading back (safe parse)...")
        levels2 = await dgmlv_levels_safe(client, MODULE_HEX)
        print(f"Updated levels: {levels2}")

    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())