// The licence and the third-party notices, as shipped beside the program.
// Python reads both files (`app.py`, `licence_documents`); nothing here calls
// the network.

export type LicenceDocuments = { licence: string; notices: string };

type LicenceApi = {
  licence_documents: () => Promise<LicenceDocuments>;
};

function api(): LicenceApi | null {
  return (window.pywebview?.api as unknown as LicenceApi) ?? null;
}

export async function licenceDocuments(): Promise<LicenceDocuments> {
  const backend = api();
  return backend ? backend.licence_documents() : { licence: "", notices: "" };
}
