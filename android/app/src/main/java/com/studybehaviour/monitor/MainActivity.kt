package com.studybehaviour.monitor

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.util.Size
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.Face
import com.google.mlkit.vision.face.FaceDetection
import com.google.mlkit.vision.face.FaceDetector
import com.google.mlkit.vision.face.FaceDetectorOptions
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

class MainActivity : ComponentActivity() {
    private lateinit var preview: PreviewView
    private lateinit var status: TextView
    private lateinit var start: Button
    private lateinit var stop: Button
    private lateinit var detector: FaceDetector
    private var provider: ProcessCameraProvider? = null
    private var analysis: ImageAnalysis? = null
    private val executor = Executors.newSingleThreadExecutor()
    private val busy = AtomicBoolean(false)
    private val sequence = AtomicLong(0)
    @Volatile private var monitoring = false
    @Volatile private var runId = ""
    private var lastAnalysisMs = 0L

    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera()
        else status.text = "Camera permission is missing. Allow Camera in Android Settings for Study Monitor USB, then press Start."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        preview = findViewById(R.id.preview)
        status = findViewById(R.id.status)
        start = findViewById(R.id.start)
        stop = findViewById(R.id.stop)
        detector = FaceDetection.getClient(
            FaceDetectorOptions.Builder()
                .setPerformanceMode(FaceDetectorOptions.PERFORMANCE_MODE_FAST)
                .setLandmarkMode(FaceDetectorOptions.LANDMARK_MODE_NONE)
                .setContourMode(FaceDetectorOptions.CONTOUR_MODE_NONE)
                .setClassificationMode(FaceDetectorOptions.CLASSIFICATION_MODE_NONE)
                .build()
        )
        start.setOnClickListener {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera()
            else permission.launch(Manifest.permission.CAMERA)
        }
        stop.setOnClickListener { stopCamera("monitoring_stopped") }
    }

    private fun startCamera() {
        if (monitoring || isFinishing || isDestroyed) return
        monitoring = true
        runId = UUID.randomUUID().toString()
        sequence.set(0)
        lastAnalysisMs = 0L
        val thisRun = runId
        start.isEnabled = false
        stop.isEnabled = true
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        status.text = "Starting camera. In Streamlit, connect the dashboard and calibrate both positions."
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (!monitoring || runId != thisRun) return@addListener
            try {
                val cameraProvider = future.get()
                provider = cameraProvider
                val selector = when {
                    cameraProvider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA) -> CameraSelector.DEFAULT_FRONT_CAMERA
                    cameraProvider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA) -> CameraSelector.DEFAULT_BACK_CAMERA
                    else -> throw IllegalStateException("No usable camera found")
                }
                val cameraPreview = Preview.Builder().build().also { it.setSurfaceProvider(preview.surfaceProvider) }
                @Suppress("DEPRECATION")
                val imageAnalysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(640, 480))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis = imageAnalysis
                imageAnalysis.setAnalyzer(executor) { image -> analyze(image, thisRun) }
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(this, selector, cameraPreview, imageAnalysis)
            } catch (exc: Exception) {
                stopCamera("camera_error")
                status.text = "Could not start camera: ${exc.message}. Check permission and whether another app is using it."
            }
        }, ContextCompat.getMainExecutor(this))
    }

    @androidx.annotation.OptIn(ExperimentalGetImage::class)
    private fun analyze(image: ImageProxy, thisRun: String) {
        val capturedMs = SystemClock.elapsedRealtime()
        if (!monitoring || runId != thisRun || capturedMs - lastAnalysisMs < 200 || !busy.compareAndSet(false, true)) {
            image.close()
            return
        }
        lastAnalysisMs = capturedMs
        val mediaImage = image.image
        if (mediaImage == null) {
            busy.set(false)
            image.close()
            return
        }
        val rotation = image.imageInfo.rotationDegrees
        val width = if (rotation == 90 || rotation == 270) image.height else image.width
        val height = if (rotation == 90 || rotation == 270) image.width else image.height
        try {
            detector.process(InputImage.fromMediaImage(mediaImage, rotation))
                .addOnSuccessListener { faces ->
                    if (monitoring && runId == thisRun) {
                        val latency = SystemClock.elapsedRealtime() - capturedMs
                        emitFaces(faces, width, height, capturedMs, latency)
                    }
                }
                .addOnFailureListener { exc ->
                    if (monitoring && runId == thisRun) {
                        emit(capturedMs, null, null, null, "detector_error", null)
                        status.text = "Face detector failed: ${exc.message}. Stop and restart; check lighting and camera availability."
                    }
                }
                .addOnCompleteListener {
                    image.close()
                    busy.set(false)
                }
        } catch (exc: Exception) {
            image.close()
            busy.set(false)
            runOnUiThread {
                if (monitoring && runId == thisRun) {
                    emit(capturedMs, null, null, null, "detector_error", null)
                    status.text = "Could not process camera frame: ${exc.message}"
                }
            }
        }
    }

    private fun emitFaces(faces: List<Face>, width: Int, height: Int, capturedMs: Long, latencyMs: Long) {
        val face = faces.singleOrNull()
        val box = face?.boundingBox
        val left = box?.left?.toDouble()?.div(width)?.coerceIn(0.0, 1.0)
        val top = box?.top?.toDouble()?.div(height)?.coerceIn(0.0, 1.0)
        val right = box?.right?.toDouble()?.div(width)?.coerceIn(0.0, 1.0)
        val bottom = box?.bottom?.toDouble()?.div(height)?.coerceIn(0.0, 1.0)
        val usable = face != null && box != null && box.width() >= 100 && box.height() >= 100 &&
            left != null && top != null && right != null && bottom != null && left < right && top < bottom
        val bounds = if (usable) JSONArray(listOf(left, top, right, bottom)) else null
        val error = if (face != null && !usable) "face_too_small_or_out_of_frame" else null
        emit(capturedMs, faces.size, if (usable) face else null, bounds, error, latencyMs)
        status.text = when {
            usable -> String.format(Locale.US, "Faces: 1 | yaw %.1f° | pitch %.1f° | roll %.1f°\nAnalysis: %d ms | USB telemetry active",
                face!!.headEulerAngleY, face.headEulerAngleX, face.headEulerAngleZ, latencyMs)
            faces.isEmpty() -> "No face detected. Keep your face visible and improve lighting."
            faces.size > 1 -> "Multiple faces detected. Streamlit will show Unknown."
            else -> "Face too small or out of frame. Move the phone closer while keeping both study positions visible."
        }
    }

    private fun emit(capturedMs: Long, count: Int?, face: Face?, bounds: JSONArray?, error: String?, latencyMs: Long?) {
        val payload = JSONObject()
            .put("schema_version", 1)
            .put("run_id", runId)
            .put("sequence", sequence.incrementAndGet())
            .put("capture_ms", capturedMs)
            .put("face_count", count ?: JSONObject.NULL)
            .put("yaw", face?.headEulerAngleY?.toDouble() ?: JSONObject.NULL)
            .put("pitch", face?.headEulerAngleX?.toDouble() ?: JSONObject.NULL)
            .put("roll", face?.headEulerAngleZ?.toDouble() ?: JSONObject.NULL)
            .put("bounds", bounds ?: JSONObject.NULL)
            .put("error", error ?: JSONObject.NULL)
            .put("inference_ms", latencyMs ?: JSONObject.NULL)
        Log.i("StudyMonitor", payload.toString())
    }

    private fun stopCamera(reason: String) {
        if (monitoring) {
            monitoring = false
            emit(SystemClock.elapsedRealtime(), null, null, null, reason, null)
        }
        analysis?.clearAnalyzer()
        provider?.unbindAll()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        start.isEnabled = true
        stop.isEnabled = false
        status.text = "Camera stopped. Press Start when you are ready."
    }

    override fun onStop() {
        stopCamera("app_backgrounded")
        super.onStop()
    }

    override fun onDestroy() {
        detector.close()
        executor.shutdown()
        super.onDestroy()
    }
}
