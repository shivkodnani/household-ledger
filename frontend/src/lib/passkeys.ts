export function base64urlToBuffer(value: string) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

export function bufferToBase64url(value: ArrayBuffer) {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function registrationOptionsFromJSON(options: PublicKeyCredentialCreationOptions) {
  const converted = { ...options, challenge: base64urlToBuffer(options.challenge as unknown as string) } as PublicKeyCredentialCreationOptions;
  converted.user = { ...converted.user, id: base64urlToBuffer(converted.user.id as unknown as string) };
  converted.excludeCredentials = (converted.excludeCredentials || []).map((item) => ({
    ...item,
    id: base64urlToBuffer(item.id as unknown as string),
  }));
  return converted;
}

export function requestOptionsFromJSON(options: PublicKeyCredentialRequestOptions) {
  return {
    ...options,
    challenge: base64urlToBuffer(options.challenge as unknown as string),
    allowCredentials: (options.allowCredentials || []).map((item) => ({
      ...item,
      id: base64urlToBuffer(item.id as unknown as string),
    })),
  } as PublicKeyCredentialRequestOptions;
}

export function credentialPayload(credential: PublicKeyCredential, registration: boolean) {
  const response = credential.response;
  const common = {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment || null,
    clientExtensionResults: {},
  };
  if (registration && response instanceof AuthenticatorAttestationResponse) {
    return {
      ...common,
      response: {
        attestationObject: bufferToBase64url(response.attestationObject),
        clientDataJSON: bufferToBase64url(response.clientDataJSON),
        transports: response.getTransports?.() || [],
      },
    };
  }
  if (response instanceof AuthenticatorAssertionResponse) {
    return {
      ...common,
      response: {
        authenticatorData: bufferToBase64url(response.authenticatorData),
        clientDataJSON: bufferToBase64url(response.clientDataJSON),
        signature: bufferToBase64url(response.signature),
        userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
      },
    };
  }
  throw new Error("Your device returned an unsupported passkey response.");
}
