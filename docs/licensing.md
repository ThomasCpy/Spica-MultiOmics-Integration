# Licence

Spica is copyright (c) 2026 Thomas Charpenay. It is available under the
[PolyForm Strict License 1.0.0](https://polyformproject.org/licenses/strict/1.0.0)
(`LICENSE`). The licence text governs; this page is a summary.

| Use | Permitted |
| --- | --- |
| Personal use, research, study, testing | Yes |
| Use by charities, schools, universities, public research and health organisations, governments | Yes |
| Commercial use | No |
| Changes, or new works based on the software | No |
| Redistribution of copies | No |

The source code is public so that people can read it and run it for a
noncommercial purpose. For any other use, contact the author through the
GitHub profile of the repository.

Spica has no activation and no licence key. All features work on any
computer.

## Third-party notices

`tools/notices.py` generates `THIRD_PARTY_NOTICES.md` at each build, from the
bundled packages. It copies their licence texts from the packages. The
optional parts (the model runtime, the document readers, DESeq2) appear only
when the build includes them.

The bundled packages use permissive licences (MIT, BSD, ISC, Apache 2.0, PSF,
OFL for the fonts), plus one MPL-2.0 package that anndata needs
(`legacy-api-wrap`, unmodified). The PyInstaller bootloader is GPL with an
exception written for this case. No GPL or AGPL package goes into the exe.
PyMuPDF is AGPL-3.0, so pdfminer.six (MIT) reads PDFs instead;
`requirements-agents.txt` records this.

`docs/licences.md` records the licence check of each data source.

## Code signing

The build signs the exe with an Authenticode certificate when one is
configured, and says "unsigned" when none is. Windows SmartScreen then trusts
the exe, users can verify its origin, and a patched exe loses its signature.

```sh
# a .pfx file
SPICA_SIGN_PFX=C:/keys/spica.pfx SPICA_SIGN_PASSWORD=... ./build.sh
# or a certificate in the Windows store, a hardware token included
SPICA_SIGN_THUMBPRINT=0123abcd... ./build.sh
```

Signing needs `signtool` from the Windows SDK (found in `Windows Kits`, or set
`SPICA_SIGNTOOL`). It uses SHA-256 and a timestamp (the DigiCert server by
default, `SPICA_SIGN_TIMESTAMP` to change it), then verifies the result. The
certificate never goes into the repository.
