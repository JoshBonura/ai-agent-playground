!macro customInstall
  !define PROVISIONER "$INSTDIR\\localmind-provisioner.exe"
  !define WHEELS_DIR  "$INSTDIR\\runtime\\wheels"
  !define REQS_DIR    "$INSTDIR\\runtime\\requirements"

  ; Env vars for the child process (provisioner)
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("LM_WHEELS_ROOT", "${WHEELS_DIR}").r0'
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("LM_REQUIREMENTS_ROOT", "${REQS_DIR}").r0'
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("LM_PROVISION_BACKENDS", "cpu,cuda,vulkan").r0'
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("LOG_RUNTIME_DEBUG", "1").r0'

  ${if} ${FileExists} ${PROVISIONER}
    DetailPrint "Provisioning runtimes..."
    nsExec::ExecToLog '"${PROVISIONER}"'
    Pop $0
    ${if} $0 != 0
      DetailPrint "Provisioning returned code $0 (continuing install)"
    ${else}
      DetailPrint "Provisioning completed."
    ${endif}
  ${else}
    DetailPrint "Provisioner not found at ${PROVISIONER}"
  ${endif}
!macroend
