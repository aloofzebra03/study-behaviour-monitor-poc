@echo off
setlocal
set "STUDY_JAVA=java.exe"
if defined JAVA_HOME set "STUDY_JAVA=%JAVA_HOME%\bin\java.exe"
"%STUDY_JAVA%" -classpath "%~dp0gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
exit /b %ERRORLEVEL%
