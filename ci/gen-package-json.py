import gen

package_json = {
    "name": "jour",
    "version": "1.0.0",
    "license": "UNLICENSED",
    "private": True,
    "dependencies": {
        "bootstrap": "5.3.3",
        "bootstrap-icons": "1.11.3",
        "htmx.org": "1.9.10",
    },
}

gen.gen(package_json, "package.json")
