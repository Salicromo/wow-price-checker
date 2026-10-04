# Crea la tarea programada que sincroniza tus subastas cada 15 minutos.
#
# Usa pythonw.exe (sin ventana) para que no te salte una consola mientras
# juegas. Para quitarla:
#
#   Unregister-ScheduledTask -TaskName "WoW subastas sync" -Confirm:$false

$ErrorActionPreference = "Stop"

$nombre = "WoW subastas sync"
$nombreVigilante = "WoW subastas vigilante"
$proyecto = $PSScriptRoot
$python = Join-Path $proyecto ".venv\Scripts\pythonw.exe"
$script = Join-Path $proyecto "sync_subastas.py"

if (-not (Test-Path $python)) {
    throw "No encuentro $python. Crea el entorno virtual primero (ver README)."
}
if (-not (Test-Path $script)) {
    throw "No encuentro $script."
}

# Con los cmdlets y no con schtasks.exe: las rutas llevan espacios, y schtasks
# parte el comando por su cuenta en cuanto los ve.
# --maquina pc: cada equipo escribe su propio fichero, para que el PC y la
# Steam Deck no se borren los personajes el uno al otro al subir.
$accion = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`" --maquina pc" `
    -WorkingDirectory $proyecto

# Un unico disparador que se repite indefinidamente. La primera pasada sale un
# minuto despues de instalarla, para poder comprobar que funciona sin esperar.
$disparador = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

# Que se ejecute tambien con el portatil a bateria, y que recupere la pasada
# perdida si el equipo estaba apagado a su hora.
$ajustes = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $nombre `
    -Action $accion `
    -Trigger $disparador `
    -Settings $ajustes `
    -Description "Sube a GitHub las subastas que exporta el addon WowAlertsExport." `
    -Force | Out-Null

# --- Vigilante: sincroniza al salir del juego ------------------------------
#
#  El addon solo vuelca sus datos cuando WoW los escribe, y eso pasa al salir al
#  selector de personajes o cerrar el juego. Esperar a la pasada de los 15
#  minutos no vale: lo normal es apagar el equipo antes, y entonces lo exportado
#  se queda sin subir hasta el siguiente encendido. Para cuando sube, las
#  subastas ya han caducado y no hay forma de saber si alguna se vendio.
#
#  En la Steam Deck esto lo hace systemd con una unidad .path. El Programador de
#  tareas de Windows no tiene disparador por cambio de fichero, asi que aqui se
#  deja un vigilante en marcha desde el inicio de sesion. No consume: mira unas
#  fechas cada cinco segundos y duerme.
$accionVigilante = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`" --maquina pc --vigilar" `
    -WorkingDirectory $proyecto

# Con -User y no con un -AtLogOn a secas: sin usuario, el disparador vale para
# el inicio de sesion de CUALQUIERA, y eso exige permisos de administrador.
# Falla con "Acceso denegado" en Register-ScheduledTask, no aqui.
$disparadorVigilante = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Sin limite de tiempo: el vigilante esta pensado para no terminar nunca. Con el
# limite por defecto, Windows lo mataria a los tres dias sin decir nada.
$ajustesVigilante = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $nombreVigilante `
    -Action $accionVigilante `
    -Trigger $disparadorVigilante `
    -Settings $ajustesVigilante `
    -Description "Sincroniza las subastas en cuanto WoW guarda los datos del addon." `
    -Force | Out-Null

# Comprobar de verdad que existe, en vez de fiarse de que no haya saltado nada.
$tarea = Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
if (-not $tarea) {
    throw "La tarea no se ha creado. Revisa los permisos de tu usuario."
}
if (-not (Get-ScheduledTask -TaskName $nombreVigilante -ErrorAction SilentlyContinue)) {
    throw "El vigilante no se ha creado. Revisa los permisos de tu usuario."
}

# Arrancarlo ya, para no tener que cerrar sesion la primera vez.
Start-ScheduledTask -TaskName $nombreVigilante

Write-Host ""
Write-Host "Tarea '$nombre' creada y verificada." -ForegroundColor Green
Write-Host "  Ejecuta:  $python"
Write-Host "  Con:      $script"
Write-Host "  Cada:     15 minutos"
Write-Host ""
Write-Host "Para lanzarla ahora mismo:" -ForegroundColor Green
Write-Host "  Start-ScheduledTask -TaskName `"$nombre`""
Write-Host ""
Write-Host "Tarea '$nombreVigilante' creada y arrancada." -ForegroundColor Green
Write-Host "  Sincroniza en cuanto sales al selector o cierras WoW."
Write-Host ""
Write-Host "Para quitarlas:" -ForegroundColor Green
Write-Host "  Unregister-ScheduledTask -TaskName `"$nombre`" -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName `"$nombreVigilante`" -Confirm:`$false"
